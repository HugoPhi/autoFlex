MAIN = main
BUILD_DIR = build

# 导出环境变量，确保所有工具都能在当前目录和 build 目录找到文件
export TEXINPUTS := .//:./$(BUILD_DIR)//:

# 采用本科论文常见编译顺序：xelatex -> bibtex -> xelatex -> xelatex
XELATEX = xelatex -shell-escape -synctex=1 -interaction=nonstopmode -file-line-error -output-directory=$(BUILD_DIR)
BIBTEX = bibtex $(BUILD_DIR)/$(MAIN)

.PHONY: all clean pdf

all: pdf

pdf:
	@mkdir -p $(BUILD_DIR)
	@mkdir -p $(BUILD_DIR)/svg-inkscape
	
	@# 针对 svg 宏包的软链接重定向方案（本地环境最稳做法）
	@if [ ! -L svg-inkscape ]; then \
		ln -s $(BUILD_DIR)/svg-inkscape svg-inkscape; \
	fi
	
	@# 执行编译：xelatex -> bibtex -> xelatex -> xelatex
	$(XELATEX) $(MAIN).tex
	$(BIBTEX)
	$(XELATEX) $(MAIN).tex
	$(XELATEX) $(MAIN).tex
	
	@# 编译完成后创建 PDF 软链接
	@ln -sf $(BUILD_DIR)/$(MAIN).pdf .
	@echo "------------------------------------------------"
	@echo "编译完成：$(MAIN).pdf 已更新"

clean:
	@if [ -d "$(BUILD_DIR)" ]; then \
		rm -f $(BUILD_DIR)/$(MAIN).aux $(BUILD_DIR)/$(MAIN).bbl $(BUILD_DIR)/$(MAIN).blg; \
		rm -f $(BUILD_DIR)/$(MAIN).fdb_latexmk $(BUILD_DIR)/$(MAIN).fls; \
		rm -f $(BUILD_DIR)/$(MAIN).log $(BUILD_DIR)/$(MAIN).toc $(BUILD_DIR)/$(MAIN).out; \
		rm -f $(BUILD_DIR)/$(MAIN).lof $(BUILD_DIR)/$(MAIN).lot $(BUILD_DIR)/$(MAIN).bcf; \
		rm -f $(BUILD_DIR)/$(MAIN).run.xml $(BUILD_DIR)/$(MAIN).xdv; \
		rm -rf $(BUILD_DIR); \
	fi
	@rm -rf svg-inkscape
	@rm -f $(MAIN).pdf
	@rm -f $(MAIN).synctex.gz