// SPDX-License-Identifier: GPL-2.0-only
/*
 * trigger6_jpeg.c -- Minimal baseline JPEG encoder for T6 output 1
 *
 * Design constraints:
 * - Integer-only math: kernel code must not rely on FPU state.
 * - Baseline sequential JPEG only: enough for the T6 decoder path.
 * - 4:2:0 subsampling: matches the vendor JPEG->NV12 transport behavior.
 * - No per-frame allocations: encode directly into the caller staging buffer.
 */

#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/string.h>

#include "trigger6_jpeg.h"

#define T6_JPEG_COMPONENTS	3
#define T6_JPEG_DCT_SCALE	16384
#define T6_JPEG_MAX_HUFF_BITS	16

struct t6_jpeg_huff_table {
	u16 codes[256];
	u8 sizes[256];
};

struct t6_jpeg_ctx {
	u8 *dst;
	size_t dst_size;
	size_t pos;
	u32 bitbuf;
	unsigned int bitcnt;
	bool overflow;
};

static struct t6_jpeg_huff_table t6_jpeg_dc_luma_table;
static struct t6_jpeg_huff_table t6_jpeg_ac_luma_table;
static struct t6_jpeg_huff_table t6_jpeg_dc_chroma_table;
static struct t6_jpeg_huff_table t6_jpeg_ac_chroma_table;
static bool t6_jpeg_huff_ready;
static DEFINE_MUTEX(t6_jpeg_huff_lock);

static const u8 t6_jpeg_zigzag[64] = {
	0, 1, 5, 6, 14, 15, 27, 28,
	2, 4, 7, 13, 16, 26, 29, 42,
	3, 8, 12, 17, 25, 30, 41, 43,
	9, 11, 18, 24, 31, 40, 44, 53,
	10, 19, 23, 32, 39, 45, 52, 54,
	20, 22, 33, 38, 46, 51, 55, 60,
	21, 34, 37, 47, 50, 56, 59, 61,
	35, 36, 48, 49, 57, 58, 62, 63,
};

static const u8 t6_jpeg_qt_luma[64] = {
	16, 11, 10, 16, 24, 40, 51, 61,
	12, 12, 14, 19, 26, 58, 60, 55,
	14, 13, 16, 24, 40, 57, 69, 56,
	14, 17, 22, 29, 51, 87, 80, 62,
	18, 22, 37, 56, 68, 109, 103, 77,
	24, 35, 55, 64, 81, 104, 113, 92,
	49, 64, 78, 87, 103, 121, 120, 101,
	72, 92, 95, 98, 112, 100, 103, 99,
};

static const u8 t6_jpeg_qt_chroma[64] = {
	17, 18, 24, 47, 99, 99, 99, 99,
	18, 21, 26, 66, 99, 99, 99, 99,
	24, 26, 56, 99, 99, 99, 99, 99,
	47, 66, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
};

static const s16 t6_jpeg_dct_matrix[8][8] = {
	{ 5793, 5793, 5793, 5793, 5793, 5793, 5793, 5793 },
	{ 8035, 6811, 4551, 1598, -1598, -4551, -6811, -8035 },
	{ 7568, 3135, -3135, -7568, -7568, -3135, 3135, 7568 },
	{ 6811, -1598, -8035, -4551, 4551, 8035, 1598, -6811 },
	{ 5793, -5793, -5793, 5793, 5793, -5793, -5793, 5793 },
	{ 4551, -8035, 1598, 6811, -6811, -1598, 8035, -4551 },
	{ 3135, -7568, 7568, -3135, -3135, 7568, -7568, 3135 },
	{ 1598, -4551, 6811, -8035, 8035, -6811, 4551, -1598 },
};

static const u8 t6_jpeg_dc_luma_bits[17] = {
	0, 0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0,
};

static const u8 t6_jpeg_dc_luma_vals[12] = {
	0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
};

static const u8 t6_jpeg_ac_luma_bits[17] = {
	0, 0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 125,
};

static const u8 t6_jpeg_ac_luma_vals[162] = {
	0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12,
	0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
	0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08,
	0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
	0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16,
	0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
	0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
	0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
	0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
	0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
	0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
	0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
	0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98,
	0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
	0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
	0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
	0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4,
	0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
	0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea,
	0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
	0xf9, 0xfa,
};

static const u8 t6_jpeg_dc_chroma_bits[17] = {
	0, 0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0,
};

static const u8 t6_jpeg_dc_chroma_vals[12] = {
	0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
};

static const u8 t6_jpeg_ac_chroma_bits[17] = {
	0, 0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 119,
};

static const u8 t6_jpeg_ac_chroma_vals[162] = {
	0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21,
	0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
	0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
	0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
	0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34,
	0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
	0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38,
	0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
	0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
	0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
	0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78,
	0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
	0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96,
	0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
	0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
	0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
	0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2,
	0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
	0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9,
	0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
	0xf9, 0xfa,
};

static inline int t6_jpeg_clamp_byte(int value)
{
	return clamp(value, 0, 255);
}

static bool t6_jpeg_put_byte(struct t6_jpeg_ctx *ctx, u8 value)
{
	if (ctx->pos >= ctx->dst_size) {
		ctx->overflow = true;
		return false;
	}

	ctx->dst[ctx->pos++] = value;
	return true;
}

static bool t6_jpeg_put_marker(struct t6_jpeg_ctx *ctx, u8 marker)
{
	return t6_jpeg_put_byte(ctx, 0xff) && t6_jpeg_put_byte(ctx, marker);
}

static bool t6_jpeg_put_be16(struct t6_jpeg_ctx *ctx, u16 value)
{
	return t6_jpeg_put_byte(ctx, value >> 8) &&
	       t6_jpeg_put_byte(ctx, value & 0xff);
}

static bool t6_jpeg_put_scan_byte(struct t6_jpeg_ctx *ctx, u8 value)
{
	if (!t6_jpeg_put_byte(ctx, value))
		return false;
	if (value == 0xff)
		return t6_jpeg_put_byte(ctx, 0x00);
	return true;
}

static bool t6_jpeg_put_bits(struct t6_jpeg_ctx *ctx, u16 code, u8 size)
{
	if (!size)
		return true;

	ctx->bitbuf |= (u32)code << (24 - ctx->bitcnt - size);
	ctx->bitcnt += size;

	while (ctx->bitcnt >= 8) {
		u8 value = ctx->bitbuf >> 24;

		if (!t6_jpeg_put_scan_byte(ctx, value))
			return false;
		ctx->bitbuf <<= 8;
		ctx->bitcnt -= 8;
	}

	return true;
}

static bool t6_jpeg_flush_bits(struct t6_jpeg_ctx *ctx)
{
	if (!ctx->bitcnt)
		return true;

	ctx->bitbuf |= (1U << (24 - ctx->bitcnt)) - 1;
	return t6_jpeg_put_scan_byte(ctx, ctx->bitbuf >> 24);
}

static void t6_jpeg_build_huff(struct t6_jpeg_huff_table *table,
			       const u8 *bits,
			       const u8 *vals,
			       size_t vals_len)
{
	u16 code = 0;
	unsigned int len;
	size_t pos = 0;

	memset(table, 0, sizeof(*table));

	for (len = 1; len <= T6_JPEG_MAX_HUFF_BITS; len++) {
		unsigned int count = bits[len];
		unsigned int i;

		for (i = 0; i < count && pos < vals_len; i++) {
			u8 sym = vals[pos++];

			table->codes[sym] = code;
			table->sizes[sym] = len;
			code++;
		}
		code <<= 1;
	}
}

static void t6_jpeg_init_huff_tables(void)
{
	/* Fast path after first successful publish of static Huffman tables. */
	if (smp_load_acquire(&t6_jpeg_huff_ready))
		return;

	mutex_lock(&t6_jpeg_huff_lock);
	/* Re-check after lock to avoid duplicate table construction races. */
	if (smp_load_acquire(&t6_jpeg_huff_ready)) {
		mutex_unlock(&t6_jpeg_huff_lock);
		return;
	}

	t6_jpeg_build_huff(&t6_jpeg_dc_luma_table, t6_jpeg_dc_luma_bits,
			   t6_jpeg_dc_luma_vals,
			   ARRAY_SIZE(t6_jpeg_dc_luma_vals));
	t6_jpeg_build_huff(&t6_jpeg_ac_luma_table, t6_jpeg_ac_luma_bits,
			   t6_jpeg_ac_luma_vals,
			   ARRAY_SIZE(t6_jpeg_ac_luma_vals));
	t6_jpeg_build_huff(&t6_jpeg_dc_chroma_table, t6_jpeg_dc_chroma_bits,
			   t6_jpeg_dc_chroma_vals,
			   ARRAY_SIZE(t6_jpeg_dc_chroma_vals));
	t6_jpeg_build_huff(&t6_jpeg_ac_chroma_table, t6_jpeg_ac_chroma_bits,
			   t6_jpeg_ac_chroma_vals,
			   ARRAY_SIZE(t6_jpeg_ac_chroma_vals));
	/* Publish all table writes before exposing the ready flag locklessly. */
	smp_store_release(&t6_jpeg_huff_ready, true);
	mutex_unlock(&t6_jpeg_huff_lock);
}

static void t6_jpeg_build_qtable(const u8 *base, unsigned int quality, u8 *out)
{
	unsigned int scale;
	unsigned int i;

	quality = clamp(quality, 1U, 100U);
	if (quality < 50)
		scale = 5000 / quality;
	else
		scale = 200 - 2 * quality;

	for (i = 0; i < 64; i++) {
		unsigned int value = DIV_ROUND_CLOSEST(base[i] * scale, 100U);

		out[i] = clamp(value, 1U, 255U);
	}
}

static int t6_jpeg_value_bits(int value, u16 *bits)
{
	unsigned int abs_value;
	int size = 0;

	if (!value) {
		*bits = 0;
		return 0;
	}

	abs_value = abs(value);
	while (abs_value) {
		size++;
		abs_value >>= 1;
	}

	if (value < 0)
		*bits = value - 1 + (1 << size);
	else
		*bits = value;

	return size;
}

static void t6_jpeg_fdct_quantize(const s16 *src, const u8 *qtable, s16 *dst)
{
	s64 row_tmp[64];
	unsigned int row, col, u;

	for (row = 0; row < 8; row++) {
		for (u = 0; u < 8; u++) {
			s64 sum = 0;

			for (col = 0; col < 8; col++)
				sum += (s64)src[row * 8 + col] * t6_jpeg_dct_matrix[u][col];
			row_tmp[row * 8 + u] = sum;
		}
	}

	for (u = 0; u < 8; u++) {
		for (row = 0; row < 8; row++) {
			s64 sum = 0;
			s64 scaled;
			int q;

			for (col = 0; col < 8; col++)
				sum += row_tmp[col * 8 + u] * t6_jpeg_dct_matrix[row][col];

			scaled = DIV_ROUND_CLOSEST_ULL(abs(sum),
					      T6_JPEG_DCT_SCALE * T6_JPEG_DCT_SCALE);
			if (sum < 0)
				scaled = -scaled;

			q = DIV_ROUND_CLOSEST((int)scaled, qtable[row * 8 + u]);
			dst[row * 8 + u] = clamp(q, -32767, 32767);
		}
	}
}

static bool t6_jpeg_encode_block(struct t6_jpeg_ctx *ctx,
				 const s16 *block,
				 const u8 *qtable,
				 const struct t6_jpeg_huff_table *dc_table,
				 const struct t6_jpeg_huff_table *ac_table,
				 int *prev_dc)
{
	s16 coeffs[64];
	int diff;
	int size;
	u16 bits;
	int zero_run = 0;
	int i;

	t6_jpeg_fdct_quantize(block, qtable, coeffs);

	diff = coeffs[0] - *prev_dc;
	*prev_dc = coeffs[0];
	size = t6_jpeg_value_bits(diff, &bits);
	if (!t6_jpeg_put_bits(ctx, dc_table->codes[size], dc_table->sizes[size]))
		return false;
	if (!t6_jpeg_put_bits(ctx, bits, size))
		return false;

	for (i = 1; i < 64; i++) {
		int coeff = coeffs[t6_jpeg_zigzag[i]];

		if (!coeff) {
			zero_run++;
			continue;
		}

		while (zero_run >= 16) {
			if (!t6_jpeg_put_bits(ctx, ac_table->codes[0xf0],
					      ac_table->sizes[0xf0]))
				return false;
			zero_run -= 16;
		}

		size = t6_jpeg_value_bits(coeff, &bits);
		if (!t6_jpeg_put_bits(ctx,
				      ac_table->codes[(zero_run << 4) | size],
				      ac_table->sizes[(zero_run << 4) | size]))
			return false;
		if (!t6_jpeg_put_bits(ctx, bits, size))
			return false;
		zero_run = 0;
	}

	if (zero_run) {
		if (!t6_jpeg_put_bits(ctx, ac_table->codes[0x00],
				      ac_table->sizes[0x00]))
			return false;
	}

	return true;
}

static void t6_jpeg_load_y_block(const u8 *src,
				 unsigned int width,
				 unsigned int height,
				 unsigned int stride,
				 unsigned int base_x,
				 unsigned int base_y,
				 s16 *block)
{
	unsigned int y, x;

	for (y = 0; y < 8; y++) {
		unsigned int py = min(base_y + y, height - 1);

		for (x = 0; x < 8; x++) {
			unsigned int px = min(base_x + x, width - 1);
			const u8 *pixel = src + py * stride + px * 4;
			int blue = pixel[0];
			int green = pixel[1];
			int red = pixel[2];
			int y_value;

			y_value = (77 * red + 150 * green + 29 * blue + 128) >> 8;
			block[y * 8 + x] = t6_jpeg_clamp_byte(y_value) - 128;
		}
	}
}

static void t6_jpeg_load_chroma_block(const u8 *src,
				      unsigned int width,
				      unsigned int height,
				      unsigned int stride,
				      unsigned int base_x,
				      unsigned int base_y,
				      s16 *cb_block,
				      s16 *cr_block)
{
	unsigned int y, x;

	for (y = 0; y < 8; y++) {
		for (x = 0; x < 8; x++) {
			int red = 0;
			int green = 0;
			int blue = 0;
			unsigned int sy, sx;

			for (sy = 0; sy < 2; sy++) {
				unsigned int py = min(base_y + y * 2 + sy, height - 1);

				for (sx = 0; sx < 2; sx++) {
					unsigned int px = min(base_x + x * 2 + sx, width - 1);
					const u8 *pixel = src + py * stride + px * 4;

					blue += pixel[0];
					green += pixel[1];
					red += pixel[2];
				}
			}

			red = DIV_ROUND_CLOSEST(red, 4);
			green = DIV_ROUND_CLOSEST(green, 4);
			blue = DIV_ROUND_CLOSEST(blue, 4);

			cb_block[y * 8 + x] =
				t6_jpeg_clamp_byte(((-43 * red - 85 * green + 128 * blue + 128) >> 8) + 128) - 128;
			cr_block[y * 8 + x] =
				t6_jpeg_clamp_byte(((128 * red - 107 * green - 21 * blue + 128) >> 8) + 128) - 128;
		}
	}
}

static bool t6_jpeg_write_headers(struct t6_jpeg_ctx *ctx,
				  unsigned int width,
				  unsigned int height,
				  const u8 *q_luma,
				  const u8 *q_chroma)
{
	unsigned int i;

	if (!t6_jpeg_put_marker(ctx, 0xd8))
		return false;

	if (!t6_jpeg_put_marker(ctx, 0xe0) || !t6_jpeg_put_be16(ctx, 16) ||
	    !t6_jpeg_put_byte(ctx, 'J') || !t6_jpeg_put_byte(ctx, 'F') ||
	    !t6_jpeg_put_byte(ctx, 'I') || !t6_jpeg_put_byte(ctx, 'F') ||
	    !t6_jpeg_put_byte(ctx, 0x00) || !t6_jpeg_put_be16(ctx, 0x0101) ||
	    !t6_jpeg_put_byte(ctx, 0x00) || !t6_jpeg_put_be16(ctx, 1) ||
	    !t6_jpeg_put_be16(ctx, 1) || !t6_jpeg_put_byte(ctx, 0x00) ||
	    !t6_jpeg_put_byte(ctx, 0x00))
		return false;

	if (!t6_jpeg_put_marker(ctx, 0xdb) || !t6_jpeg_put_be16(ctx, 67) ||
	    !t6_jpeg_put_byte(ctx, 0x00))
		return false;
	for (i = 0; i < 64; i++) {
		if (!t6_jpeg_put_byte(ctx, q_luma[t6_jpeg_zigzag[i]]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xdb) || !t6_jpeg_put_be16(ctx, 67) ||
	    !t6_jpeg_put_byte(ctx, 0x01))
		return false;
	for (i = 0; i < 64; i++) {
		if (!t6_jpeg_put_byte(ctx, q_chroma[t6_jpeg_zigzag[i]]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xc0) || !t6_jpeg_put_be16(ctx, 17) ||
	    !t6_jpeg_put_byte(ctx, 8) ||
	    !t6_jpeg_put_be16(ctx, height) || !t6_jpeg_put_be16(ctx, width) ||
	    !t6_jpeg_put_byte(ctx, T6_JPEG_COMPONENTS) ||
	    !t6_jpeg_put_byte(ctx, 1) || !t6_jpeg_put_byte(ctx, 0x22) ||
	    !t6_jpeg_put_byte(ctx, 0x00) || !t6_jpeg_put_byte(ctx, 2) ||
	    !t6_jpeg_put_byte(ctx, 0x11) || !t6_jpeg_put_byte(ctx, 0x01) ||
	    !t6_jpeg_put_byte(ctx, 3) || !t6_jpeg_put_byte(ctx, 0x11) ||
	    !t6_jpeg_put_byte(ctx, 0x01))
		return false;

	if (!t6_jpeg_put_marker(ctx, 0xc4) || !t6_jpeg_put_be16(ctx, 31) ||
	    !t6_jpeg_put_byte(ctx, 0x00))
		return false;
	for (i = 1; i <= 16; i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_dc_luma_bits[i]))
			return false;
	}
	for (i = 0; i < ARRAY_SIZE(t6_jpeg_dc_luma_vals); i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_dc_luma_vals[i]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xc4) || !t6_jpeg_put_be16(ctx, 181) ||
	    !t6_jpeg_put_byte(ctx, 0x10))
		return false;
	for (i = 1; i <= 16; i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_ac_luma_bits[i]))
			return false;
	}
	for (i = 0; i < ARRAY_SIZE(t6_jpeg_ac_luma_vals); i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_ac_luma_vals[i]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xc4) || !t6_jpeg_put_be16(ctx, 31) ||
	    !t6_jpeg_put_byte(ctx, 0x01))
		return false;
	for (i = 1; i <= 16; i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_dc_chroma_bits[i]))
			return false;
	}
	for (i = 0; i < ARRAY_SIZE(t6_jpeg_dc_chroma_vals); i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_dc_chroma_vals[i]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xc4) || !t6_jpeg_put_be16(ctx, 181) ||
	    !t6_jpeg_put_byte(ctx, 0x11))
		return false;
	for (i = 1; i <= 16; i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_ac_chroma_bits[i]))
			return false;
	}
	for (i = 0; i < ARRAY_SIZE(t6_jpeg_ac_chroma_vals); i++) {
		if (!t6_jpeg_put_byte(ctx, t6_jpeg_ac_chroma_vals[i]))
			return false;
	}

	if (!t6_jpeg_put_marker(ctx, 0xda) || !t6_jpeg_put_be16(ctx, 12) ||
	    !t6_jpeg_put_byte(ctx, T6_JPEG_COMPONENTS) ||
	    !t6_jpeg_put_byte(ctx, 1) || !t6_jpeg_put_byte(ctx, 0x00) ||
	    !t6_jpeg_put_byte(ctx, 2) || !t6_jpeg_put_byte(ctx, 0x11) ||
	    !t6_jpeg_put_byte(ctx, 3) || !t6_jpeg_put_byte(ctx, 0x11) ||
	    !t6_jpeg_put_byte(ctx, 0x00) || !t6_jpeg_put_byte(ctx, 0x3f) ||
	    !t6_jpeg_put_byte(ctx, 0x00))
		return false;

	return true;
}

int t6_jpeg_encode_xrgb8888(const u8 *src,
			    unsigned int width,
			    unsigned int height,
			    unsigned int stride,
			    unsigned int quality,
			    u8 *dst,
			    size_t dst_size)
{
	struct t6_jpeg_ctx ctx = { };
	u8 q_luma[64];
	u8 q_chroma[64];
	s16 y_block[64];
	s16 cb_block[64];
	s16 cr_block[64];
	unsigned int mcu_x, mcu_y;
	int prev_dc_y = 0;
	int prev_dc_cb = 0;
	int prev_dc_cr = 0;

	if (!src || !dst || !width || !height || stride < width * 4)
		return -EINVAL;

	ctx.dst = dst;
	ctx.dst_size = dst_size;

	t6_jpeg_init_huff_tables();
	t6_jpeg_build_qtable(t6_jpeg_qt_luma, quality, q_luma);
	t6_jpeg_build_qtable(t6_jpeg_qt_chroma, quality, q_chroma);

	if (!t6_jpeg_write_headers(&ctx, width, height, q_luma, q_chroma))
		return -E2BIG;

	for (mcu_y = 0; mcu_y < DIV_ROUND_UP(height, 16U); mcu_y++) {
		for (mcu_x = 0; mcu_x < DIV_ROUND_UP(width, 16U); mcu_x++) {
			t6_jpeg_load_y_block(src, width, height, stride,
					    mcu_x * 16, mcu_y * 16,
					    y_block);
			if (!t6_jpeg_encode_block(&ctx, y_block, q_luma,
						   &t6_jpeg_dc_luma_table,
						   &t6_jpeg_ac_luma_table,
						   &prev_dc_y))
				return -E2BIG;

			t6_jpeg_load_y_block(src, width, height, stride,
					    mcu_x * 16 + 8, mcu_y * 16,
					    y_block);
			if (!t6_jpeg_encode_block(&ctx, y_block, q_luma,
						   &t6_jpeg_dc_luma_table,
						   &t6_jpeg_ac_luma_table,
						   &prev_dc_y))
				return -E2BIG;

			t6_jpeg_load_y_block(src, width, height, stride,
					    mcu_x * 16, mcu_y * 16 + 8,
					    y_block);
			if (!t6_jpeg_encode_block(&ctx, y_block, q_luma,
						   &t6_jpeg_dc_luma_table,
						   &t6_jpeg_ac_luma_table,
						   &prev_dc_y))
				return -E2BIG;

			t6_jpeg_load_y_block(src, width, height, stride,
					    mcu_x * 16 + 8, mcu_y * 16 + 8,
					    y_block);
			if (!t6_jpeg_encode_block(&ctx, y_block, q_luma,
						   &t6_jpeg_dc_luma_table,
						   &t6_jpeg_ac_luma_table,
						   &prev_dc_y))
				return -E2BIG;

			t6_jpeg_load_chroma_block(src, width, height, stride,
						 mcu_x * 16, mcu_y * 16,
						 cb_block, cr_block);

			if (!t6_jpeg_encode_block(&ctx, cb_block, q_chroma,
						   &t6_jpeg_dc_chroma_table,
						   &t6_jpeg_ac_chroma_table,
						   &prev_dc_cb) ||
			    !t6_jpeg_encode_block(&ctx, cr_block, q_chroma,
						   &t6_jpeg_dc_chroma_table,
						   &t6_jpeg_ac_chroma_table,
						   &prev_dc_cr))
				return -E2BIG;
		}
	}

	if (!t6_jpeg_flush_bits(&ctx) || !t6_jpeg_put_marker(&ctx, 0xd9))
		return -E2BIG;

	return ctx.overflow ? -E2BIG : ctx.pos;
}
