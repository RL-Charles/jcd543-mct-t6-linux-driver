KVER ?= $(shell uname -r)
KSRC ?= /lib/modules/$(KVER)/build
KDIR := $(CURDIR)

modules:
	make -C $(KSRC) M=$(KDIR) modules

clean:
	make -C $(KSRC) M=$(KDIR) clean

install: modules
	make -C $(KSRC) M=$(KDIR) modules_install
	depmod -a

.PHONY: modules clean install
