#
# Files and directories
#
WORKDIR ?= $(CURDIR)
RESULTS ?= $(WORKDIR)
PLOT_FORMAT ?= svg
PLOT ?= $(WORKDIR)/$(notdir $(WORKDIR)).$(PLOT_FORMAT)

#
# Parameters
#
KRAFT_TOKEN ?=
PROXY_HOST ?= 192.168.3.181
PROXY_PORT ?= 7890
PROXY_URL ?= http://$(PROXY_HOST):$(PROXY_PORT)
USE_PROXY ?=

#
# Tools
#
DOCKER ?= docker
TIME ?= /usr/bin/time

#
# Proxy configuration for docker build/run
#
DOCKER_BUILD_PROXY_ARGS =
DOCKER_RUN_PROXY_ENV =
ifdef USE_PROXY
DOCKER_BUILD_PROXY_ARGS += --build-arg HTTP_PROXY=$(PROXY_URL) \
                           --build-arg HTTPS_PROXY=$(PROXY_URL) \
                           --build-arg ALL_PROXY=$(PROXY_URL) \
                           --build-arg NO_PROXY=localhost,127.0.0.1,$(PROXY_HOST)
DOCKER_RUN_PROXY_ENV += -e HTTP_PROXY=$(PROXY_URL) \
                        -e HTTPS_PROXY=$(PROXY_URL) \
                        -e ALL_PROXY=$(PROXY_URL) \
                        -e NO_PROXY=localhost,127.0.0.1,$(PROXY_HOST)
endif

#
# Targets
#
.PHONY: all
all: prepare run plot

.PHONY: prepare
prepare:
	$(TIME) $(DOCKER) build -f $(WORKDIR)/flexos-porting.dockerfile \
		--build-arg GITHUB_TOKEN="$(KRAFT_TOKEN)" \
		$(DOCKER_BUILD_PROXY_ARGS) \
		--tag flexos-porting $(WORKDIR)

.PHONY: run
run:
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged \
		--security-opt seccomp:unconfined -ti \
		$(DOCKER_RUN_PROXY_ENV) \
		flexos-porting bash

.PHONY: plot
plot:
	@-

.PHONY: clean
clean:
	@-

.PHONY: properclean
properclean:
	$(DOCKER) image rm -f flexos-porting
	$(DOCKER) image prune -f
