import streamlit as st

from nber_radar import (
    Paper,
    fetch_nber_papers,
    list_feedback,
    papers_to_dataframe,
    render_markdown_digest,
    save_feedback,
    score_papers,
    decompose_chinese_query,
    score_one_paper_custom,
)

st.set_page_config(page_title="NBER Public Econ Radar", layout="wide")

st.title("NBER Public Econ Radar")
st.caption("NBER 文献筛选 + 公共经济与管理相关性排序 + 3 条短 highlights")

with st.sidebar:
    st.header("筛选设置")
    st.caption("数据源：NBER 公开元数据仓库（每周自动更新）")

    # ── 自定义搜索主题（中文输入）──
    with st.expander("自定义搜索主题（中文）", expanded=True):
        custom_query = st.text_input(
            "输入学科或主题",
            placeholder="例：财政税收政策评估、数字经济治理、教育公平...",
            label_visibility="collapsed",
        )
        if custom_query:
            st.caption("正在拆词...")
            en_kws = decompose_chinese_query(custom_query)
            if en_kws:
                st.success(f"拆为 {len(en_kws)} 个英文关键词")
                st.code(" ".join(en_kws), language="text")
            else:
                st.warning("未识别到有效关键词，请尝试其他表述。")
        custom_score_weight = st.slider("自定义关键词权重", 1, 5, 2, step=1,
                                         help="每个匹配的自定义关键词加多少分，越高则自定义主题越优先")
        custom_search = st.button("自定义搜索", type="primary",
                                   disabled=not (custom_query and decompose_chinese_query(custom_query)))

    st.divider()

    max_papers = st.slider("抓取数量", 10, 100, 50, step=10)
    min_score = st.slider("最低相关性", 0, 100, 35, step=5)
    st.markdown("建议：日常推送用 50 分以上，选题扫描用 35 分以上。")
    default_run = st.button("默认搜索（公共经济与管理）", type="secondary")

if "papers" not in st.session_state:
    st.session_state.papers = []
if "search_mode" not in st.session_state:
    st.session_state.search_mode = "默认"
if "custom_kws" not in st.session_state:
    st.session_state.custom_kws = []

# 默认搜索
if default_run:
    with st.spinner("正在从 NBER 元数据仓库抓取新论文并筛选……"):
        raw = fetch_nber_papers(max_papers=max_papers)
        st.session_state.papers = score_papers(raw, min_score=min_score)
        st.session_state.search_mode = "默认"
        st.session_state.custom_kws = []

# 自定义搜索
if custom_search and custom_query:
    with st.spinner(f"正在抓取并匹配自定义主题：{custom_query}……"):
        en_kws = decompose_chinese_query(custom_query)
        if en_kws:
            raw = fetch_nber_papers(max_papers=max_papers)
            base = score_papers(raw, min_score=0)  # 不设最低分，让自定义关键词来提分
            custom_scored = [score_one_paper_custom(p, en_kws, weight=custom_score_weight) for p in base]
            custom_scored = [p for p in custom_scored if p.score >= min_score]
            custom_scored = sorted(custom_scored, key=lambda p: (p.score, p.published), reverse=True)
            st.session_state.papers = custom_scored
            st.session_state.search_mode = f"自定义：{custom_query}"
            st.session_state.custom_kws = en_kws

papers = st.session_state.papers

# 搜索模式标识
if st.session_state.search_mode != "默认":
    st.info(f"当前模式：{st.session_state.search_mode}")
    if st.session_state.custom_kws:
        st.caption(f"英文关键词：{' '.join(st.session_state.custom_kws)}")

if papers:
    df = papers_to_dataframe(papers)
    c1, c2, c3 = st.columns(3)
    c1.metric("相关论文", len(df))
    c2.metric("A类强相关", int((df["level"] == "A").sum()))
    c3.metric("平均相关性", round(float(df["score"].mean()), 1))

    md = render_markdown_digest(papers)
    st.download_button("下载 Markdown 推送稿", data=md, file_name="nber_public_econ_digest.md", mime="text/markdown")
    st.download_button("下载 CSV", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="nber_public_econ.csv", mime="text/csv")

    st.subheader("筛选结果")
    for idx, p in enumerate(papers):
        with st.container(border=True):
            left, right = st.columns([4, 1])
            with left:
                st.markdown(f"### {idx + 1}. [{p.title}]({p.url})")
                st.write(f"**等级：** {p.level} ｜ **相关性：** {p.score}/100 ｜ **NBER：** {p.nber_id or 'N/A'}")
                st.write(f"**作者：** {p.authors or 'N/A'}")
                st.write(f"**日期：** {p.published or 'N/A'}")
                st.write(f"**一句话：** {p.reason}")
                st.write("**Highlights：** " + " ｜ ".join(p.highlights))
                if p.abstract:
                    with st.expander("查看摘要/来源文本"):
                        st.write(p.abstract[:2500])
            with right:
                if st.button("收藏", key=f"save_{idx}"):
                    save_feedback(p, "saved")
                    st.success("已收藏")
                if st.button("忽略", key=f"ignore_{idx}"):
                    save_feedback(p, "ignored")
                    st.info("已记录")

    with st.expander("查看表格"):
        st.dataframe(df, use_container_width=True)
else:
    st.info("点击左侧「默认搜索」或「自定义搜索」开始。")

st.subheader("我的反馈记录")
try:
    fb = list_feedback()
    if len(fb):
        st.dataframe(fb, use_container_width=True)
    else:
        st.caption("暂无收藏或忽略记录。")
except Exception as exc:
    st.warning(f"反馈库暂不可用：{exc}")
