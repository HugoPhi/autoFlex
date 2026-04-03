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
# These should be contiguous on the same NUMA node
NOISOLED_CPU1 ?= 1
NOISOLED_CPU2 ?= 2
NOISOLED_CPU3 ?= 3
NOISOLED_CPU4 ?= 4
ISOLED_CPU1 ?= 5
ISOLED_CPU2 ?= 6
ISOLED_CPU3 ?= 7

#
# Tools
#
GNUPLOT ?= gnuplot
DOCKER ?= docker

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
	$(DOCKER) build -f $(WORKDIR)/flexos-iperf.dockerfile \
		--build-arg GITHUB_TOKEN="$(KRAFT_TOKEN)" \
		$(DOCKER_BUILD_NETWORK) \
		$(DOCKER_BUILD_PROXY_ARGS) \
		--tag flexos-iperf $(WORKDIR)

.PHONY: run
run:
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged \
		--security-opt seccomp:unconfined -ti \
		$(DOCKER_RUN_PROXY_ENV) \
		flexos-iperf \
		/root/run.sh $(ISOLED_CPU1) $(ISOLED_CPU2) $(ISOLED_CPU3) \
		$(NOISOLED_CPU1) $(NOISOLED_CPU2) $(NOISOLED_CPU3) $(NOISOLED_CPU4)

.PHONY: plot
plot:
	rm -rf $(PLOT)
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged -ti \
		ghcr.io/project-flexos/flexos-ae-plot $(GNUPLOT) /out/iperf.plot
	mv $(WORKDIR)/iperf.svg $(PLOT)

.PHONY: clean
clean:
	rm -rf results $(PLOT)

.PHONY: properclean
properclean: clean
	$(DOCKER) image rm -f flexos-iperf
	$(DOCKER) image prune -f
