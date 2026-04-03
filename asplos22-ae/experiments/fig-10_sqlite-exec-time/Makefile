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
ISOLED_CPU1 ?= 5
ISOLED_CPU2 ?= 6

#
# Tools
#
GNUPLOT ?= gnuplot
DOCKER ?= docker
TIME ?= /usr/bin/time

#
# Proxy configuration for docker build/run
#
DOCKER_BUILD_NETWORK = --network default
DOCKER_BUILD_PROXY_ARGS =
DOCKER_RUN_PROXY_ENV =
ifdef USE_PROXY
# Use host network for build to allow kraft to reach proxy at 127.0.0.1:7890
DOCKER_BUILD_NETWORK = --network host
# Pass proxy env vars for any curl/git inside build
DOCKER_BUILD_PROXY_ARGS += --build-arg HTTP_PROXY=http://127.0.0.1:$(PROXY_PORT) \
                           --build-arg HTTPS_PROXY=http://127.0.0.1:$(PROXY_PORT) \
                           --build-arg ALL_PROXY=http://127.0.0.1:$(PROXY_PORT) \
                           --build-arg NO_PROXY=localhost,127.0.0.1
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
	$(TIME) $(DOCKER) build -f $(WORKDIR)/flexos-sqlite.dockerfile \
		--build-arg GITHUB_TOKEN="$(KRAFT_TOKEN)" \
		$(DOCKER_BUILD_NETWORK) \
		$(DOCKER_BUILD_PROXY_ARGS) \
		--tag flexos-sqlite $(WORKDIR)

.PHONY: run
run:
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged \
		--security-opt seccomp:unconfined -ti \
		$(DOCKER_RUN_PROXY_ENV) \
		flexos-sqlite \
		/root/run.sh $(ISOLED_CPU1) $(ISOLED_CPU2)

.PHONY: plot
plot:
	rm -rf $(PLOT)
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged -ti \
		ghcr.io/project-flexos/flexos-ae-plot $(GNUPLOT) /out/sqlite.plot
	mv $(WORKDIR)/sqlite.svg $(PLOT)

.PHONY: clean
clean:
	rm -rf results $(PLOT)

.PHONY: properclean
properclean: clean
	$(DOCKER) image rm -f flexos-sqlite
	$(DOCKER) image prune -f
