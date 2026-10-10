#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轨道 A：在官方源码树里重新打开 CMCC RAX3000Q 的 Wi-Fi。

背景（上游 commit d592680cc501cd7decdffb50b80c964d128c22ef，PR openwrt#22763）：
    &q6v5_wcss / &wifi / &wifi1 在 DTS 里被明确写成 status = "disabled"，
    理由是原文 "Due to the limited 256 MiB RAM, ath11k is disabled in the DTS to
    avoid OOM issues on this device."
    也就是说：官方固件在这台机器上默认是没有 Wi-Fi 的。

做法：
    不删改原 DTS，只在文件**末尾追加 device-tree overlay**（后面出现的 status 覆盖先前的），
    这样既幂等、又不依赖正则去啃 356 行的 DTS。

    要开哪些标签，直接**从设备 DTS 自己解析**：凡是 `&label { ... status = "disabled" ... };`
    且 label 名字像无线的（wifi/wcss/q6v5/ath11k），就给它写一句 status = "okay"。
    —— 这样做的好处是不需要标签定义在源码树里（&wifi 这类节点可能定义在内核 dtsi 里），
    出现在设备 DTS 中就意味着标签一定存在，overlay 一定编译得过。

用法：
    python3 enable-wifi.py /path/to/openwrt
环境变量：
    ENABLE_WIFI=0   直接跳过（等价于 workflow 输入 enable_wifi=false）
退出码：
    0 = 正常（包括「无需修改」）；1 = 明确出错（工作流里已用 `|| true` 兜底，不会因此中断构建）
"""

import os
import re
import sys

# 像无线节点的标签名（用于从设备 DTS 里挑出该重开的节点）
WIFI_LABEL_RE = re.compile(r"(wifi|wcss|q6v5|ath11k|wcn|qcn)", re.I)

# 兜底候选（当设备 DTS 里解析不出任何被禁用的无线节点时，才去源码树里找这些标签）
CANDIDATES = ["q6v5_wcss", "wifi", "wifi1", "wifi2", "wifi3"]

MARKER = "rax3000q-ipq50xx-build: enable wifi"

OVERLAY_TMPL = """
/*
 * ---- {marker} ----
 * 上游为规避 256 MiB RAM 的 OOM 风险，把 Wi-Fi 在 DTS 里 disabled 了。
 * 下面用 overlay 重新打开（256 MiB 机器上如果实测不稳/OOM，
 * 把 workflow 输入 enable_wifi 设为 false 重新编译即可回到官方行为）。
 */
{body}
"""


# --------------------------------------------------------------------------- 定位 DTS
def find_dts(root):
    direct = [
        os.path.join(root, "target/linux/qualcommax/dts/ipq5018-rax3000q.dts"),
        os.path.join(root, "files/arch/arm64/boot/dts/qcom/ipq5018-rax3000q.dts"),
    ]
    for c in direct:
        if os.path.isfile(c):
            return c

    search_roots = [
        os.path.join(root, "target/linux/qualcommax"),
        os.path.join(root, "files/arch/arm64/boot/dts/qcom"),
    ]
    for base in search_roots:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for f in filenames:
                if f.endswith(".dts") and "rax3000q" in f.lower():
                    return os.path.join(dirpath, f)
    return None


# ------------------------------------------------------------------- 解析 DTS 里的节点
def blocks(text):
    """产出 (label, body) —— 匹配 `&label {` 到行首的 `};`。"""
    pat = re.compile(r"&([A-Za-z0-9_\-]+)\s*\{(.*?)\n\};", re.S)
    for m in pat.finditer(text):
        yield m.group(1), m.group(2)


def status_of(body):
    m = re.search(r'status\s*=\s*"([^"]+)"', body)
    return m.group(1) if m else None


def label_defined_in_tree(root, label):
    """兜底用：标签是否在 qualcommax 的 dts/dtsi 里出现过。"""
    pat = re.compile(r"^\s*&%s\s*\{" % re.escape(label), re.M)
    bases = [
        os.path.join(root, "target/linux/qualcommax"),
        os.path.join(root, "files/arch/arm64/boot/dts/qcom"),
    ]
    for base in bases:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for f in filenames:
                if not f.endswith((".dts", ".dtsi", ".dtsinc")):
                    continue
                try:
                    txt = open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                if pat.search(txt):
                    return True
    return False


def main():
    if os.environ.get("ENABLE_WIFI", "1") in ("0", "false", "False", "no", "NO"):
        print("[enable-wifi] ENABLE_WIFI=0，跳过（保持官方「无 Wi-Fi」行为）")
        return 0

    root = sys.argv[1] if len(sys.argv) > 1 else "."
    dts = find_dts(root)
    if not dts:
        print("[enable-wifi] !! 找不到 ipq5018-rax3000q.dts"
              "（官方可能改了路径/文件名），未做任何修改")
        return 1
    print("[enable-wifi] 设备 DTS = %s" % dts)

    txt = open(dts, encoding="utf-8", errors="replace").read()

    if MARKER in txt:
        print("[enable-wifi] 已有 overlay，跳过（幂等）")
        return 0

    # 1) 从设备 DTS 自己解析：哪些无线节点被 disabled / 已经 okay
    disabled, already_ok = [], []
    for label, body in blocks(txt):
        st = status_of(body)
        if st is None:
            continue
        if not WIFI_LABEL_RE.search(label):
            continue
        if st.lower() == "disabled":
            disabled.append(label)
            print("    发现 &%s { status = \"disabled\" }" % label)
        elif st.lower() in ("okay", "ok"):
            already_ok.append(label)

    labels = list(dict.fromkeys(disabled))  # 去重且保序

    # 2) 兜底：设备 DTS 里没解析出被禁用的无线节点时，用候选标签在源码树里找
    if not labels:
        print("[enable-wifi] 设备 DTS 里没有解析出被禁用的无线节点，改用候选标签兜底")
        for lab in CANDIDATES:
            if label_defined_in_tree(root, lab):
                labels.append(lab)

    if not labels:
        print("[enable-wifi] !! 没有任何可打开的无线节点（可能上游已经改成 enabled，"
              "或 DTS 结构变了）——未做修改，请检查上面的解析输出")
        return 1

    if already_ok:
        print("[enable-wifi] 这些节点本来就是 okay，无需处理：%s" % ", ".join(already_ok))

    body = "".join('&%s {\n\tstatus = "okay";\n};\n' % lab for lab in labels)

    with open(dts, "a", encoding="utf-8") as f:
        f.write(OVERLAY_TMPL.format(marker=MARKER, body=body))

    print("[enable-wifi] 已追加 overlay，打开的节点：%s" % ", ".join(labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
