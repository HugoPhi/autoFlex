TEX=main.tex
BUILD_DIR=build
PDF=$(BUILD_DIR)/$(TEX:.tex=.pdf)
LATEXMK=latexmk

.PHONY: all pdf clean distclean

all: pdf

pdf:
	mkdir -p $(BUILD_DIR)
	$(LATEXMK) -f -pdfxe -shell-escape -interaction=nonstopmode -file-line-error -outdir=$(BUILD_DIR) -auxdir=$(BUILD_DIR) $(TEX) || true

clean:
	$(LATEXMK) -C -outdir=$(BUILD_DIR) -auxdir=$(BUILD_DIR) $(TEX) || true
	rm -rf svg-inkscape

distclean:
	rm -rf $(BUILD_DIR)
