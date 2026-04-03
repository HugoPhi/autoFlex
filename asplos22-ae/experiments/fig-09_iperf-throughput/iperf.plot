#!/usr/bin/gnuplot

reset

if (!exists("PLOT_KIND")) PLOT_KIND = "svg"
if (!exists("PLOT_OUT")) PLOT_OUT = "./fig-09_iperf-throughput.svg"

if (PLOT_KIND eq "png") {
    set terminal pngcairo enhanced size 820,280 font 'Times New Roman,11'
} else {
    set terminal svg enhanced size 820,280 font 'Times New Roman,11'
}
set output PLOT_OUT

set object 1 rectangle from screen 0,0 to screen 1,1 behind \
    fillcolor rgb '#ffffff' fillstyle solid 1.0 noborder
set object 2 rectangle from screen 0,0 to screen 1,1 front \
    fillstyle empty border lc rgb '#111111' lw 2.0

set border linecolor rgb '#111111' linewidth 1.8

# Make the x axis labels easier to read.
set xtics font ",9" textcolor rgb '#262626' nomirror
set ytics font ",9" textcolor rgb '#262626' nomirror

# make sure that the legend doesn't take too much space
set key inside bottom right samplen 1 font ',9' width -5

# ensure that y label doesn't take too much space
set ylabel "iPerf throughput (Gb/s)" offset 2.5,0
set xlabel "Receive Buffer Size" offset 0,0.5

# remove useless margins
#set bmargin 2
set lmargin 7
set rmargin 1
set tmargin 0.5

# use logscale, display powers of two
set logscale x 2
set logscale y 2
set format x '2^{%L}'

# line styles
set style line 1 \
    linecolor rgb '#4c78a8' \
    linetype 1 linewidth 1.5 \
    pointtype 7 pointsize 0.28
set style line 2 \
    linecolor rgb '#1f9d8a' \
    linetype 1 linewidth 1.5 \
    pointtype 5 pointsize 0.28
set style line 3 \
    linecolor rgb '#e67e22' \
    linetype 1 linewidth 1.5 \
    pointtype 11 pointsize 0.28
set style line 4 \
    linecolor rgb '#d95f02' \
    linetype 1 linewidth 1.5 \
    pointtype 9 pointsize 0.28
set style line 5 \
    linecolor rgb '#72b7b2' \
    linetype 1 linewidth 1.5 \
    pointtype 13 pointsize 0.28

# use this to set the range, although the default one seems to be good here
#set yrange [0:3.5]
set xrange [16:16384]

plot './results/iperf.dat' \
        index 0 with linespoints linestyle 1 t "Unikraft", \
     '' index 1 with linespoints linestyle 2 t "FlexOS NONE", \
     '' index 3 with linespoints linestyle 3 t "FlexOS MPK2-light", \
     '' index 2 with linespoints linestyle 4 t "FlexOS MPK2-dss", \
     '' index 4 with linespoints linestyle 5 t "FlexOS EPT2"
