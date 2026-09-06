# SPDX-License-Identifier: GPL-2.0-only
CC ?= cc
CFLAGS := -std=gnu11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer
.PHONY: check

check: build/test_match build/test_refresh build/test_query
	./build/test_match
	./build/test_refresh
	./build/test_query

build/test_match: test_match.c ../kernel/trigger6_match.h
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ test_match.c

build/test_refresh: test_refresh.c ../kernel/trigger6_refresh.h
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ test_refresh.c

build/test_query: test_query.c ../kernel/trigger6_query.h
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ test_query.c
