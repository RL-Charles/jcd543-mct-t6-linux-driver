KVER ?= $(shell uname -r)
KSRC ?= /lib/modules/$(KVER)/build

modules:
	make -C $(KSRC) M=$(PWD) modules

clean:
	make -C $(KSRC) M=$(PWD) clean

install: modules
	make -C $(KSRC) M=$(PWD) modules_install
	depmod -a

.PHONY: modules clean install
