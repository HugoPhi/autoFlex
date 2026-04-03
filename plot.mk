# Generic Makefile template for plotting scripts
# To use: include this file in your experiment's Makefile
# Configure PLOTS, PYTHON_SCRIPTS, and other variables

# Default PNG DPI if not set
PLOT_PNG_DPI ?= 300

# Directory structure for outputs
SVG_DIR ?= results/svg
PNG_DIR ?= results/png
DATA_DIR ?= results/data

# Create directories helper
ensure_dirs = mkdir -p $(SVG_DIR) $(PNG_DIR) $(DATA_DIR)

# Generic plot target that handles Python script execution
# Usage: $(call plot_python_script,script_name,input,output_base,extra_args)
define plot_python_script
	$(ensure_dirs)
	python3 $(1) $(3) --out-svg $(SVG_DIR)/$(4).svg --out-png $(PNG_DIR)/$(4).png --png-dpi $(PLOT_PNG_DPI) $(5)
endef

# Help target
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  make plot-python      - Generate all plots (SVG + PNG)"
	@echo "  make plot-svg         - Generate only SVG plots"
	@echo "  make plot-png         - Generate only PNG plots"
	@echo "  make plot-clean       - Remove all generated plots"
	@echo ""
	@echo "Configuration:"
	@echo "  PLOT_PNG_DPI=$(PLOT_PNG_DPI)  - PNG resolution in DPI"
	@echo "  SVG_DIR=$(SVG_DIR)"
	@echo "  PNG_DIR=$(PNG_DIR)"
	@echo ""
	@echo "Override with: make plot-python PLOT_PNG_DPI=150"

# Clean target
.PHONY: plot-clean
plot-clean:
	rm -f $(SVG_DIR)/* $(PNG_DIR)/*

.PHONY: plot-svg
plot-svg:
	@echo "SVG generation not implemented for generic template"

.PHONY: plot-png
plot-png:
	@echo "PNG generation not implemented for generic template"

.PHONY: plot-python
plot-python: plot-clean
	@echo "Python plot generation - implement in your Makefile"
