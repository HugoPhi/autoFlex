# You can easily build it with the following command:
# $ docker build --tag flexos-iperf -f flexos-iperf.dockerfile .
#
# If the build fails because you are rate-limited by GitHub, generate an app
# token () and run instead:
# $ docker build --build-arg UK_KRAFT_GITHUB_TOKEN="<YOUR TOKEN>" --tag flexos-iperf
#
# and run with:
# $ docker run --privileged --security-opt seccomp:unconfined -ti flexos-iperf bash
#
# (--security-opt seccomp:unconfined to limit docker overhead)

FROM ghcr.io/project-flexos/flexos-ae-base:latest

ARG GITHUB_TOKEN=
ENV UK_KRAFT_GITHUB_TOKEN=${GITHUB_TOKEN}

WORKDIR /root/.unikraft/apps
# 重新正式安装 kraft 以修复 broken 的元数据，并确保运行环境正常
RUN pip3 install /root/kraft

# 运行清理逻辑，并允许它失败（防止因为没有 Makefile 而中断构建）
RUN kraftcleanup || true

RUN mv /root/.unikraft /root/flexos

##############
# Finish

WORKDIR /root
