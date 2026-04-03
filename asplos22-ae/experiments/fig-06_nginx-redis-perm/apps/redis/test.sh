#!/bin/bash
set -xe
DIR=$1
if [[ "${DIR}" == "" ]]; then
  echo "Usage: $0 DIR"
  exit 1
fi

WAYFINDER_CORE_ID0=10
WAYFINDER_CORE_ID1=12
WAYFINDER_CORE_ID2=14

# 设置性能模式
echo "performance" > /sys/devices/system/cpu/cpu${WAYFINDER_CORE_ID0}/cpufreq/scaling_governor
echo "performance" > /sys/devices/system/cpu/cpu${WAYFINDER_CORE_ID1}/cpufreq/scaling_governor
echo "performance" > /sys/devices/system/cpu/cpu${WAYFINDER_CORE_ID2}/cpufreq/scaling_governor

QEMU_GUEST=${QEMU_GUEST:-./support/qemu-guest}
BRIDGE=asplosae10
BRIDGE_IP="10.99.1.1"
UNIKERNEL_INITRD=${UNIKERNEL_INITRD:-./redis.cpio}
UNIKERNEL_IP="10.99.1.2"
REDIS_BENCHMARK_MODE=${REDIS_BENCHMARK_MODE:-docker}
REDIS_BENCH_IMAGE=${REDIS_BENCH_IMAGE:-ghcr.io/project-flexos/flexos-ae-base:latest}
NUM_PARALLEL_CONNS=${NUM_PARALLEL_CONNS:-30}
# NUM_PARALLEL_CONNS=${NUM_PARALLEL_CONNS:-10}
ITERATIONS=${ITERATIONS:-5}
RESULTS=${RESULTS:-./results.txt}
# CHUNKS=${CHUNKS:-5 50 500}
CHUNKS=${CHUNKS:-5}
NUM_REQUESTS=${NUM_REQUESTS:-100000}
# NUM_REQUESTS=${NUM_REQUESTS:-100}

if [[ ! -f ${RESULTS} ]]; then
  echo "TASKID,CHUNK,ITERATION,METHOD,VALUE" > ${RESULTS}
fi

function cleanup {
  echo "Cleaning up..."
  ifconfig ${BRIDGE} down || true
  brctl delbr ${BRIDGE} || true
  pkill -9 -f qemu-system-x86_64 || true
}

if [[ "${REDIS_BENCHMARK_MODE}" == "docker" ]]; then
  REDIS_BENCH_CMD=(docker run --rm --network host --cpuset-cpus "${WAYFINDER_CORE_ID2}" "${REDIS_BENCH_IMAGE}" redis-benchmark)
else
  REDIS_BENCH_CMD=(taskset -c ${WAYFINDER_CORE_ID2} redis-benchmark)
fi

trap "cleanup" EXIT

echo "Creating bridge..."
brctl addbr ${BRIDGE} || true
ifconfig ${BRIDGE} ${BRIDGE_IP}
ifconfig ${BRIDGE} up

for D in ${DIR}/*; do
  if [[ ! -d ${D} ]]; then continue; fi

  TASKID=$(basename ${D})
  UNIKERNEL_IMAGE=${D}/usr/src/unikraft/apps/redis/build/redis_kvm-x86_64

  if [[ ! -f ${UNIKERNEL_IMAGE} ]]; then continue; fi

  for CHUNK in ${CHUNKS}; do
    for ((I=1; I<=${ITERATIONS};I++)) do
      echo "Starting unikernel..."

      taskset -c ${WAYFINDER_CORE_ID0} \
        ${QEMU_GUEST} \
          -k ${UNIKERNEL_IMAGE} \
          -x \
          -m 1024 \
          -i ${UNIKERNEL_INITRD} \
          -b ${BRIDGE} \
          -p ${WAYFINDER_CORE_ID1} \
          -a "netdev.ipv4_addr=${UNIKERNEL_IP} netdev.ipv4_gw_addr=${BRIDGE_IP} netdev.ipv4_subnet_mask=255.255.255.0 vfs.rootdev=ramfs -- /redis.conf"


      # echo "Waiting for network (${UNIKERNEL_IP})..."
      # for j in {1..30}; do
      #     if ping -c 1 -W 1 ${UNIKERNEL_IP} > /dev/null; then
      #         echo "Network is UP!"
      #         break
      #     fi
      #     sleep 1
      # done

      # 轮询 6379 端口，直到 Redis 真正吐出数据
      for i in {1..30}; do
          if nc -z -w 1 ${UNIKERNEL_IP} 6379; then
              echo "Redis is UP and Listening on 6379!"
              break
          fi
          echo "Redis not ready yet, retrying ($i/30)..."
          sleep 1
      done

      # echo "Starting experiment..."
      # # 注意：宿主机需要安装 redis-benchmark (sudo apt install redis-tools)
      # taskset -c ${WAYFINDER_CORE_ID2} \
      #     redis-benchmark \
      #       -h ${UNIKERNEL_IP} -p 6379 \
      #       -n ${NUM_REQUESTS} \
      #       --csv -q -c ${NUM_PARALLEL_CONNS} -k 1 -P 16 -t get,set \
      #       | awk -v prefix="${TASKID},${CHUNK},${I}" '{ print prefix "," $0 }' >> ${RESULTS}
      #
      # sed -i 's/"//g' ${RESULTS}
      # pkill -9 -f qemu-system-x86_64 || true


      echo "Starting experiment..."
      
      # 设定一个总超时时间（例如 60 秒）
      # 如果 redis-benchmark 60秒没出结果，timeout 会自动结束它
      set +e # 临时关闭报错退出，防止 timeout 导致整个脚本停止
      
        timeout --foreground 6000s \
          "${REDIS_BENCH_CMD[@]}" \
            -h ${UNIKERNEL_IP} -p 6379 \
            -n ${NUM_REQUESTS} \
            --csv -q -c ${NUM_PARALLEL_CONNS} -k 1 -P 16 -t get,set \
            | awk -v prefix="${TASKID},${CHUNK},${I}" '{ print prefix "," $0 }' >> ${RESULTS}
            # 我们使用 -F',' 指定逗号分隔，并只打印前两列原始数据 ($1 是 Method, $2 是 RPS)
            # awk -F',' -v prefix="${TASKID},${CHUNK},${I}" '{ 
            #     if ($1 != "\"test\"") { # 跳过标题行
            #         print prefix "," $1 "," $2 
            #     }
            # }' >> ${RESULTS}
      
      # 检查上一个命令的状态码
      if [ $? -eq 124 ]; then
          echo "[TIMEOUT] Task ${TASKID} timed out after 60s, skipping..."
          # 在结果文件记录一下超时，方便后续画图时剔除
          echo "${TASKID},${CHUNK},${I},TIMEOUT,0" >> ${RESULTS}
      fi
      
      set -e # 重新开启报错退出
      
      # 无论成功还是超时，都要彻底杀掉当前的 QEMU 进程，释放内存和网桥网卡
      echo "Cleaning up current task..."
      pkill -9 -f qemu-system-x86_64 || true
      sleep 1 # 给系统一点喘息时间
    done
  done
done
