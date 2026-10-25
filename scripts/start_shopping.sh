#!/usr/bin/env bash
# 起 shopping（或 shopping_admin）容器、等它就绪、把 Magento 的 base_url 改成本机地址。
#
#   bash scripts/start_shopping.sh              # 默认 shopping, 端口 7770
#   PORT=7780 NAME=shopping_admin IMG=shopping_admin_final_0719 bash scripts/start_shopping.sh
#
# 为什么要改 base_url：Magento 把站点域名写死在数据库里，不改的话页面里的链接
# 全指向镜像构建时的地址，agent 点进去就是 404/无法访问，任务必然失败。
set -euo pipefail

PORT="${PORT:-7770}"
NAME="${NAME:-shopping}"
IMG="${IMG:-shopping_final_0712}"
URL="http://127.0.0.1:${PORT}"

if ! docker image inspect "$IMG" >/dev/null 2>&1; then
  echo "[error] 本地没有镜像 $IMG"
  echo "        先跑：bash scripts/pull_images.sh shopping"
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  echo "[info] 容器 $NAME 已存在，启动它"
  docker start "$NAME" >/dev/null
else
  echo "[info] 创建容器 $NAME（$IMG -> $URL）"
  docker run --name "$NAME" -p "${PORT}:80" -d "$IMG" >/dev/null
fi

echo "[info] 等站点就绪（首次启动 Magento 要 30–90 秒）"
code="000"
for i in $(seq 1 36); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" || true)
  case "$code" in
    200|301|302) echo "[ok] $URL 返回 $code（第 ${i} 次探测）"; break ;;
  esac
  sleep 5
done
if [ "$code" = "000" ]; then
  echo "[error] 180 秒内没起来。看日志：docker logs --tail 50 $NAME"
  exit 1
fi

echo "[info] 把 base_url 改成 $URL"
docker exec "$NAME" /var/www/magento2/bin/magento setup:store-config:set --base-url="$URL" || \
  echo "[warn] setup:store-config 失败（镜像路径可能不同，继续）"
docker exec "$NAME" mysql -u magentouser -pMyPassword magentodb \
  -e "UPDATE core_config_data SET value='$URL/' WHERE path='web/secure/base_url';" || \
  echo "[warn] 直接改数据库失败，继续"
docker exec "$NAME" /var/www/magento2/bin/magento cache:flush || \
  echo "[warn] cache:flush 失败，继续"

echo
echo "[done] 浏览器打开 $URL 应该能看到电商首页"
echo "       容器内验证：curl -s -o /dev/null -w '%{http_code}\\n' '$URL'"
echo
echo "下一步（跑第一个任务，不带记忆）："
echo "  cd WebArena"
echo "  export PYTHONPATH=\"\$HOME/reasoning-bank/third_party:\$PYTHONPATH\""
echo "  set -a; . ../.env; set +a"
echo "  .venv/bin/python run.py --task_name webarena.21 --model_name deepseek-chat --results_path ./results"
