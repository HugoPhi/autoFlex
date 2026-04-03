#
# Files and directories
#
WORKDIR ?= $(CURDIR)
RESULTS ?= $(WORKDIR)/results
PLOT_FORMAT ?= svg
PLOT-DSS ?= $(RESULTS)/$(notdir $(WORKDIR))-a.$(PLOT_FORMAT)
PLOT-LATENCY ?= $(RESULTS)/$(notdir $(WORKDIR))-b.$(PLOT_FORMAT)

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
PYTHON ?= $(shell (python -V >/dev/null 2>&1 && echo python) || (python3 -V >/dev/null 2>&1 && echo python3) || echo python3)
PIP ?= $(PYTHON) -m pip
PY_DEPS ?= matplotlib numpy
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
all: prepare run plot-python

.PHONY: prepare-flexos
prepare-flexos:
	$(TIME) $(DOCKER) build -f $(WORKDIR)/flexos-microbenchmarks.dockerfile \
		--build-arg GITHUB_TOKEN="$(KRAFT_TOKEN)" \
		$(DOCKER_BUILD_NETWORK) \
		$(DOCKER_BUILD_PROXY_ARGS) \
		--tag flexos-microbenchmarks $(WORKDIR)

linux-latency:
	git clone https://github.com/project-flexos/app-flexos-microbenchmarks.git
	mv app-flexos-microbenchmarks linux-latency

.PHONY: prepare-linux
prepare-linux: linux-latency
	$(TIME) make linux -C linux-latency

.PHONY: prepare
prepare: prepare-flexos prepare-linux

.PHONY: run-flexos
run-flexos:
	$(DOCKER) run --rm -v $(WORKDIR):/out --privileged \
		--security-opt seccomp:unconfined -ti \
		$(DOCKER_RUN_PROXY_ENV) \
		flexos-microbenchmarks \
		/root/run.sh $(ISOLED_CPU1) $(ISOLED_CPU2)

.PHONY: run-linux
run-linux:
	mkdir -p $(RESULTS)
	$(WORKDIR)/tools/benchmark_linux.sh $(RESULTS) $(WORKDIR)/linux-latency $(ISOLED_CPU1)

.PHONY: run
run: run-flexos run-linux

.PHONY: pydeps
pydeps:
	@$(PYTHON) -c "import matplotlib, numpy" >/dev/null 2>&1 && exit 0; \
	if $(PYTHON) -c "import sys; print(int(getattr(sys, 'base_prefix', sys.prefix) != sys.prefix))" | grep -q 1; then \
		$(PIP) install $(PY_DEPS); \
	else \
		echo "[pydeps] Missing matplotlib/numpy in current python."; \
		echo "[pydeps] Activate your venv, then run: python -m pip install matplotlib numpy"; \
		exit 1; \
	fi

.PHONY: plot-python
plot-python: pydeps
	$(PYTHON) ./results/plot_fig11.py \
		--results-dir ./results \
		--out-prefix ./results/fig-11_flexos-alloc-latency

.PHONY: clean
clean:
	rm -f $(RESULTS)/fig-11_flexos-alloc-latency-a.svg $(RESULTS)/fig-11_flexos-alloc-latency-b.svg

.PHONY: properclean
properclean: clean
	$(DOCKER) image rm -f flexos-microbenchmarks
	$(DOCKER) image prune -f
