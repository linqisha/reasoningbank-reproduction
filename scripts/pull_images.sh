#!/usr/bin/env bash
# 拉取 WebArena 官方环境镜像。
#
# 背景：官方 tar 链接已失效（metis 502、archive.org 条目下架、Google Drive 国内不可达），
# 但社区把同样的镜像推到了 Docker Hub 的 webarenaimages/* 下，内容与 tar 等价。
#
# 用法（Ubuntu/WSL，需要 docker 可用）：
#   bash scripts/pull_images.sh shopping
#   bash scripts/pull_images.sh shopping_admin
#   bash scripts/pull_images.sh reddit
#   bash scripts/pull_images.sh gitlab
#
# Docker Hub 直连慢/失败时，脚本会依次尝试国内中转站（拉完自动打回标准 tag）。
set -euo pipefail

SITE="${1:-shopping}"

case "$SITE" in
  shopping)
    REPO="webarenaimages/shopping_final_0712"
    TAG="shopping_final_0712"
    SIZE="45GB" ;;
  shopping_admin)
    REPO="webarenaimages/shopping_admin_final_0719"
    TAG="shopping_admin_final_0719"
    SIZE="2.2GB" ;;
  reddit)
    REPO="webarenaimages/postmill-populated-exposed-withimg"
    TAG="postmill-populated-exposed-withimg"
    SIZE="45GB" ;;
  gitlab)
    REPO="webarenaimages/gitlab-populated-final"
    TAG="gitlab-populated-final-port8023"
    SIZE="48GB" ;;
  *)
    echo "不认识的站点: $SITE（可选: shopping / shopping_admin / reddit / gitlab）"
    exit 1 ;;
esac

echo "==> $SITE: $REPO  (约 $SIZE，解压后)"
echo "    磁盘检查："
df -h /var/lib/docker 2>/dev/null || true
docker system df 2>/dev/null || true

if docker image inspect "$TAG" >/dev/null 2>&1; then
  echo "[ok] 本地已有 $TAG，跳过拉取"
  exit 0
fi

# 第一个为空 = Docker Hub 直连；后面是常见的国内中转（会失效，所以试多个）
MIRRORS=("" "docker.m.daocloud.io/" "docker.1ms.run/" "dockerproxy.net/")

for m in "${MIRRORS[@]}"; do
  src="${m}${REPO}:latest"
  echo "==> docker pull $src"
  if docker pull "$src"; then
    if [ -n "$m" ]; then
      docker tag "$src" "$TAG"
      echo "[ok] 已打 tag: $TAG"
    else
      docker tag "$REPO:latest" "$TAG" 2>/dev/null || true
    fi
    echo "[done] $TAG 就绪"
    echo
    echo "下一步（shopping 示例）："
    echo "  docker run --name shopping -p 7770:80 -d $TAG"
    echo "  docker exec shopping /var/www/magento2/bin/magento setup:store-config:set --base-url=\"http://127.0.0.1:7770\""
    echo "  docker exec shopping mysql -u magentouser -pMyPassword magentodb -e 'UPDATE core_config_data SET value=\"http://127.0.0.1:7770/\" WHERE path = \"web/secure/base_url\";'"
    echo "  docker exec shopping /var/www/magento2/bin/magento cache:flush"
    exit 0
  fi
  echo "[warn] $src 拉取失败，换下一个源"
done

cat <<'EOF'
[error] 所有源都失败。可选办法：
  1. Docker Desktop → Settings → Docker Engine，在 JSON 里加：
       "registry-mirrors": ["https://docker.m.daocloud.io", "https://docker.1ms.run"]
     然后 Apply & restart，重跑本脚本
  2. 用代理：Docker Desktop → Settings → Resources → Proxies
  3. 换成瘦身镜像（5.4GB，评分口径不同，只适合验证流程）：
       docker pull am1n3e/webarena-verified-shopping
       docker tag am1n3e/webarena-verified-shopping shopping_final_0712
EOF
exit 1
