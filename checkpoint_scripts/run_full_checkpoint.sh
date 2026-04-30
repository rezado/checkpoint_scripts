#!/bin/bash
set -euo pipefail

###############################################################################
# 完整 Checkpoint 流程一键脚本
#
# 用法:
#   bash run_full_checkpoint.sh [config.yaml]
#
# 默认使用 config_full_checkpoint.yaml
# 流程: Build(initramfs->kernel->opensbi->gcpt) -> Profiling(BBV) -> Cluster(SimPoint) -> Checkpoint
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="${1:-config_full_checkpoint.yaml}"

# ==================== 1. 环境准备 ====================
echo "========== [1/5] 加载环境 =========="
source /nfs/home/share/workload_env/env.sh
export RISCV_ROOTFS_HOME=/nfs/home/wujiabin/work/checkpoint_scripts/riscv-rootfs

for var in NEMU_HOME QEMU_HOME LINUX_HOME OPENSBI_HOME GCPT_HOME RISCV_ROOTFS_HOME; do
    if [[ ! -d "${!var}" ]]; then
        echo "ERROR: $var=${!var} 不存在"; exit 1
    fi
done

SIMPOINT="$NEMU_HOME/resource/simpoint/simpoint_repo/bin/simpoint"
QEMU="$QEMU_HOME/build/qemu-system-riscv64"
[[ -x "$SIMPOINT" ]] || { echo "ERROR: simpoint 不存在: $SIMPOINT"; exit 1; }
[[ -x "$QEMU" ]]     || { echo "ERROR: qemu 不存在: $QEMU"; exit 1; }

echo "  NEMU_HOME=$NEMU_HOME"
echo "  QEMU_HOME=$QEMU_HOME"
echo "  RISCV_ROOTFS_HOME=$RISCV_ROOTFS_HOME"
echo "  CONFIG=$CONFIG"

count_checkpoints_py() {
    python3 - "$1" "$2" <<'PY'
import sys
from run_single_bin_checkpoint import count_checkpoints

print(count_checkpoints(sys.argv[1], sys.argv[2]))
PY
}

validate_outputs_py() {
    python3 - "$1" "$2" <<'PY'
import sys
from run_single_bin_checkpoint import count_checkpoints, validate_outputs

validate_outputs(sys.argv[1], sys.argv[2])
print(count_checkpoints(sys.argv[1], sys.argv[2]))
PY
}

# ==================== 2. Build + Profiling ====================
echo ""
echo "========== [2/5] Build + Profiling (python generate_checkpoint.py) =========="
python3 generate_checkpoint.py --config "$CONFIG" 2>&1 | tee full_checkpoint_run.log

# 找到本次生成的 archive 目录 (最新的)
ARCHIVE=$(ls -dt archive/*/ 2>/dev/null | head -1)
if [[ -z "$ARCHIVE" ]]; then
    echo "ERROR: 找不到 archive 目录"; exit 1
fi
ARCHIVE="${ARCHIVE%/}"
echo "  Archive: $ARCHIVE"

# 从 config 解析 workload 名称
SPEC_APPS=$(python3 -c "
import yaml, json, sys
cfg = yaml.safe_load(open('$CONFIG'))
base = cfg['base_config']
cpu2017 = base.get('CPU2017', False)
json_file = 'spec_info/spec17.json' if cpu2017 else 'spec_info/spec06.json'
spec_info = json.load(open(json_file))
spec_app_list = base.get('spec_app_list')
apps_str = base.get('spec_apps')
if spec_app_list:
    with open(spec_app_list, encoding='utf-8') as handle:
        selected = [line.strip() for line in handle if line.strip()]
elif apps_str:
    requested = {item for item in apps_str.split(',') if item}
    selected = [k for k in spec_info if spec_info[k]['base_name'] in requested]
else:
    selected = list(spec_info.keys())
print(' '.join(selected))
")
if [[ -z "$SPEC_APPS" ]]; then
    echo "ERROR: 配置未解析到任何 workload"; exit 1
fi
echo "  Workloads: $SPEC_APPS"

# ==================== 3. 验证 Profiling 结果 ====================
echo ""
echo "========== [3/5] 验证 Profiling 结果 =========="
ALL_PROFILING_OK=true
for app in $SPEC_APPS; do
    BBV="$ARCHIVE/profiling-0/$app/simpoint_bbv.gz"
    if [[ -f "$BBV" ]]; then
        echo "  [OK] $app: $(ls -lh "$BBV" | awk '{print $5}')"
    else
        echo "  [FAIL] $app: simpoint_bbv.gz 不存在"
        ALL_PROFILING_OK=false
    fi
done
$ALL_PROFILING_OK || { echo "ERROR: Profiling 未完成"; exit 1; }

# ==================== 4. Cluster (SimPoint 聚类) ====================
echo ""
echo "========== [4/5] Cluster (SimPoint 聚类) =========="
for app in $SPEC_APPS; do
    echo "  Clustering: $app ..."
    CLUSTER_DIR="$ARCHIVE/cluster-0-0/$app"
    mkdir -p "$CLUSTER_DIR"
    mkdir -p "$ARCHIVE/logs/cluster-0-0/$app"

    BBV="$ARCHIVE/profiling-0/$app/simpoint_bbv.gz"
    MAXK=30
    [[ "$app" == *"xalancbmk"* ]] && MAXK=100

    SEEDKM=$((RANDOM * RANDOM % 900000 + 100000))
    SEEDPROJ=$((RANDOM * RANDOM % 900000 + 100000))

    "$SIMPOINT" \
        -loadFVFile "$BBV" \
        -saveSimpoints "$CLUSTER_DIR/simpoints0" \
        -saveSimpointWeights "$CLUSTER_DIR/weights0" \
        -inputVectorsGzipped \
        -maxK "$MAXK" \
        -numInitSeeds 2 \
        -iters 1000 \
        -seedkm "$SEEDKM" \
        -seedproj "$SEEDPROJ" \
        > "$ARCHIVE/logs/cluster-0-0/$app/cluster.out.log" 2>&1 \
        || { echo "  [FAIL] $app cluster 失败"; exit 1; }

    NUM_SIMPOINTS=$(wc -l < "$CLUSTER_DIR/simpoints0")
    echo "  [OK] $app: $NUM_SIMPOINTS 个聚类点"
done

# ==================== 5. Checkpoint (QEMU 打 checkpoint) ====================
echo ""
echo "========== [5/5] Checkpoint (QEMU 打 Checkpoint) =========="
COPIES=$(python3 -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['base_config'].get('copies', 2))")
ARCHIVE_ABS=$(realpath "$ARCHIVE")

for app in $SPEC_APPS; do
    echo "  Checkpointing: $app ..."
    CPT_LOG_DIR="$ARCHIVE/logs/checkpoint-0-0-0/$app"
    mkdir -p "$CPT_LOG_DIR"

    "$QEMU" \
        -bios "$ARCHIVE_ABS/gcpt_bins/$app" \
        -M "nemu,simpoint-path=$ARCHIVE_ABS/cluster-0-0,workload=$app,cpt-interval=20000000,output-base-dir=$ARCHIVE_ABS,config-name=checkpoint-0-0-0,checkpoint-mode=SimpointCheckpoint" \
        -nographic \
        -m 8G \
        -smp "$COPIES" \
        -cpu "rv64,v=true,vlen=128,h=false,sv39=true,sv48=false,sv57=false,sv64=false" \
        > "$CPT_LOG_DIR/checkpoint.out.log" 2> "$CPT_LOG_DIR/checkpoint.err.log" \
        || echo "  [WARN] $app checkpoint 退出码非0 (继续检查产物)"

    if ! NUM_CPT=$(validate_outputs_py "$ARCHIVE_ABS" "$app"); then
        echo "  [FAIL] $app checkpoint 产物校验失败"
        exit 1
    fi
    CPT_SIZE=$(du -sh "$ARCHIVE/checkpoint-0-0-0/$app" 2>/dev/null | awk '{print $1}')
    echo "  [OK] $app: $NUM_CPT 个 checkpoint, 总大小 $CPT_SIZE"
done

# ==================== 6. Postprocess Metadata ====================
echo ""
echo "========== [6/6] Postprocess Metadata =========="
python3 dump_result.py \
    --base-path "$ARCHIVE_ABS" \
    --spec-apps "$(echo "$SPEC_APPS" | tr ' ' ',')" \
    --times "1,1,1" \
    --ids "0,0,0"
echo "  [OK] Generated $ARCHIVE/checkpoint-0-0-0/cluster-0-0.json"
echo "  [OK] Generated $ARCHIVE/checkpoint-0-0-0/checkpoint.lst"

# ==================== 完成 ====================
echo ""
echo "=========================================="
echo "  全部完成!"
echo "  Archive: $ARCHIVE"
echo ""
echo "  结果概览:"
for app in $SPEC_APPS; do
    NUM_CPT=$(count_checkpoints_py "$ARCHIVE_ABS" "$app")
    CPT_SIZE=$(du -sh "$ARCHIVE/checkpoint-0-0-0/$app" 2>/dev/null | awk '{print $1}')
    echo "    $app: $NUM_CPT checkpoints ($CPT_SIZE)"
done
echo "=========================================="
