"""Core logic for NBER Public Econ Radar.

This module fetches NBER working paper metadata from the public TSV metadata
repository (https://data.nber.org/nber_paper_chapter_metadata/tsv/), filters
papers for public economics and public management interests, and produces
short Chinese highlights for quick literature scanning.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import io
import os
import re
import smtplib
import sqlite3
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

METADATA_BASE = "http://data.nber.org/nber_paper_chapter_metadata/tsv"
METADATA_WEEKS = 12  # fetch papers from this many weeks back
USER_AGENT = "NBER Public Econ Radar/0.1 (+personal research alert tool)"

# Map NBER program codes to full names
PROGRAM_CODES = {
    "AP": "Asset Pricing",
    "CF": "Corporate Finance",
    "CH": "Children and Families",
    "DAE": "Development of the American Economy",
    "DEV": "Development Economics",
    "ED": "Economics of Education",
    "EEE": "Environment and Energy Economics",
    "EFG": "Economic Fluctuations and Growth",
    "EH": "Economic History",
    "HC": "Health Care",
    "HE": "Health Economics",
    "IFM": "International Finance and Macroeconomics",
    "IO": "Industrial Organization",
    "ITI": "International Trade and Investment",
    "LE": "Law and Economics",
    "LS": "Labor Studies",
    "ME": "Monetary Economics",
    "PE": "Public Economics",
    "POL": "Political Economy",
    "PR": "Productivity, Innovation, and Entrepreneurship",
    "URB": "Urban Economics",
}


@dataclasses.dataclass
class Paper:
    nber_id: str
    title: str
    authors: str = ""
    abstract: str = ""
    url: str = ""
    published: str = ""
    programs: str = ""
    source: str = "nber"
    score: int = 0
    level: str = "C"
    reason: str = ""
    highlights: Tuple[str, str, str] = ("政策研究", "公共议题", "待读摘要")
    _matched_kws: List[str] = dataclasses.field(default_factory=list)
    matched_topics: Tuple[str, ...] = ()


TOPIC_KEYWORDS: Dict[str, Dict[str, Any]] = {
    "公共财政": {
        "highlight": "公共财政",
        "keywords": [
            "public finance", "tax", "taxation", "income tax", "corporate tax",
            "property tax", "tax credit", "eitc", "fiscal", "budget", "deficit",
            "debt", "government spending", "public spending", "expenditure",
            "subsidy", "transfer", "welfare", "social security", "medicaid",
            "medicare", "redistribution", "public debt", "fiscal policy",
        ],
    },
    "公共管理": {
        "highlight": "公共管理",
        "keywords": [
            "public administration", "public sector", "bureaucracy", "governance",
            "state capacity", "government agency", "civil service", "officials",
            "procurement", "contracting", "compliance", "enforcement", "corruption",
            "decentralization", "local government", "municipality", "county",
            "regulation", "regulatory", "administrative",
        ],
    },
    "政策评估": {
        "highlight": "政策评估",
        "keywords": [
            "policy", "policies", "reform", "program", "evaluation", "impact",
            "effect", "effects", "causal", "causality", "difference-in-differences",
            "difference in differences", "did", "regression discontinuity", "rdd",
            "randomized", "experiment", "field experiment", "quasi-experimental",
            "instrumental variable", "event study", "natural experiment",
        ],
    },
    "教育政策": {
        "highlight": "教育政策",
        "keywords": [
            "education", "school", "schools", "teacher", "teachers", "student",
            "students", "college", "university", "tuition", "scholarship",
            "voucher", "charter school", "school finance", "human capital",
        ],
    },
    "健康政策": {
        "highlight": "健康政策",
        "keywords": [
            "health", "healthcare", "health care", "hospital", "insurance",
            "medicaid", "medicare", "public health", "mental health", "mortality",
            "physician", "medical", "drug", "opioid", "pandemic",
        ],
    },
    "劳动就业": {
        "highlight": "劳动就业",
        "keywords": [
            "labor", "labour", "employment", "unemployment", "wage", "wages",
            "minimum wage", "job", "jobs", "worker", "workers", "training",
            "labor market", "earnings", "occupation", "union",
        ],
    },
    "城市治理": {
        "highlight": "城市治理",
        "keywords": [
            "urban", "city", "cities", "housing", "rent", "zoning", "land use",
            "transport", "transportation", "commute", "infrastructure", "policing",
            "crime", "neighborhood", "local labor market", "migration",
        ],
    },
    "分配公平": {
        "highlight": "分配公平",
        "keywords": [
            "inequality", "poverty", "redistribution", "mobility", "income distribution",
            "wealth", "racial", "race", "gender", "stratification", "opportunity",
            "discrimination", "intergenerational", "social mobility",
        ],
    },
    "环境规制": {
        "highlight": "环境规制",
        "keywords": [
            "environment", "energy", "climate", "carbon", "pollution", "emissions",
            "clean air", "renewable", "electricity", "fuel", "regulation", "epa",
        ],
    },
    "政治经济": {
        "highlight": "政治经济",
        "keywords": [
            "political economy", "election", "voting", "voter", "democracy",
            "campaign", "legislature", "politician", "party", "political",
            "media", "polarization", "lobbying", "public opinion",
        ],
    },
    "中国研究": {
        "highlight": "中国研究",
        "keywords": [
            "china", "chinese", "hukou", "prefecture", "cadre", "local officials",
            "state-owned", "soe", "county", "province", "provincial",
        ],
    },
}

METHOD_KEYWORDS: Dict[str, List[str]] = {
    "因果识别": ["causal", "causality", "natural experiment", "quasi-experimental", "instrumental variable", "rdd", "regression discontinuity", "difference-in-differences", "difference in differences", "event study", "randomized", "experiment"],
    "准实验": ["quasi-experimental", "natural experiment", "difference-in-differences", "difference in differences", "rdd", "event study"],
    "实证检验": ["estimate", "estimates", "empirical", "data", "evidence", "administrative data"],
}

PROGRAM_HINTS = {
    "Public Economics": 18,
    "Political Economy": 15,
    "Economics of Education": 15,
    "Health Economics": 15,
    "Health Care": 15,
    "Labor Studies": 14,
    "Urban Economics": 14,
    "Law and Economics": 12,
    "Environment and Energy Economics": 12,
    "Children": 12,
    "Race and Stratification": 12,
    "Organizational Economics": 8,
    "Market Design": 8,
}

GENERAL_FALLBACK_HIGHLIGHTS = ["政策评估", "公共议题", "因果识别", "实证检验", "制度影响"]

# ── 中文 → 英文关键词词典（用于自定义搜索拆词）──
CHINESE_TO_ENGLISH: Dict[str, List[str]] = {
    "财政": ["public finance", "fiscal", "fiscal policy", "government spending"],
    "税收": ["tax", "taxation", "tax policy", "income tax", "corporate tax"],
    "税": ["tax", "taxation", "tax policy"],
    "债务": ["public debt", "fiscal deficit", "government debt"],
    "赤字": ["fiscal deficit", "budget deficit", "public debt"],
    "预算": ["budget", "government budget", "fiscal policy"],
    "社保": ["social security", "medicare", "medicaid", "welfare"],
    "福利": ["welfare", "social welfare", "redistribution", "transfer"],
    "转移支付": ["transfer", "intergovernmental transfer", "fiscal transfer"],
    "地方政府债务": ["local government debt", "municipal debt", "fiscal decentralization"],
    "财政分权": ["fiscal decentralization", "intergovernmental", "local government"],
    "公共管理": ["public administration", "public sector", "governance", "bureaucracy"],
    "治理": ["governance", "public administration", "state capacity"],
    "官僚": ["bureaucracy", "bureaucratic", "civil service", "officials"],
    "政府": ["government", "public sector", "state", "local government"],
    "地方政府": ["local government", "municipality", "county government", "decentralization"],
    "官员": ["officials", "cadre", "civil service", "bureaucracy"],
    "腐败": ["corruption", "rent-seeking", "governance"],
    "寻租": ["rent-seeking", "corruption", "lobbying"],
    "政绩": ["performance", "cadre evaluation"],
    "晋升": ["promotion", "cadre", "political incentive"],
    "政策": ["policy", "policies", "reform", "public policy"],
    "评估": ["evaluation", "impact", "effect", "program evaluation"],
    "改革": ["reform", "policy reform", "institutional change"],
    "因果": ["causal", "causality", "causal inference"],
    "实证": ["empirical", "evidence", "estimate", "causal inference"],
    "准实验": ["quasi-experimental", "natural experiment", "difference-in-differences"],
    "工具变量": ["instrumental variable", "iv", "causal identification"],
    "断点回归": ["regression discontinuity", "rdd", "causal inference"],
    "双重差分": ["difference-in-differences", "difference in differences", "did"],
    "教育": ["education", "school", "schooling", "human capital", "college"],
    "人力资本": ["human capital", "education", "skill", "training"],
    "健康": ["health", "healthcare", "public health", "health insurance"],
    "医疗": ["healthcare", "medicare", "medicaid", "health insurance"],
    "劳动": ["labor", "labour", "employment", "labor market", "worker"],
    "就业": ["employment", "unemployment", "labor market", "job"],
    "工资": ["wage", "wages", "minimum wage", "earnings"],
    "最低工资": ["minimum wage", "labor policy"],
    "不平等": ["inequality", "income distribution", "wealth inequality"],
    "贫困": ["poverty", "redistribution", "social mobility", "inequality"],
    "代际": ["intergenerational", "social mobility", "intergenerational mobility"],
    "流动": ["mobility", "social mobility", "intergenerational mobility"],
    "城市": ["urban", "city", "cities", "urban economics"],
    "住房": ["housing", "rent", "zoning", "housing market"],
    "土地": ["land", "land use", "zoning", "property"],
    "基础设施": ["infrastructure", "public investment", "transportation"],
    "交通": ["transportation", "commute", "infrastructure"],
    "环境": ["environment", "environmental", "pollution", "climate"],
    "能源": ["energy", "renewable", "electricity", "fuel"],
    "污染": ["pollution", "emissions", "environmental regulation"],
    "气候": ["climate", "climate change", "carbon"],
    "政治": ["political", "politics", "political economy"],
    "选举": ["election", "voting", "voter", "political economy"],
    "民主": ["democracy", "political participation", "voting"],
    "数字": ["digital", "digital economy", "technology", "data"],
    "数字经济": ["digital economy", "technology", "platform", "digital"],
    "平台": ["platform", "digital platform", "technology"],
    "人工智能": ["artificial intelligence", "ai", "automation", "technology"],
    "技术": ["technology", "innovation", "digital", "automation"],
    "创新": ["innovation", "technology", "research and development", "rd"],
    "中国": ["china", "chinese", "china studies", "chinese economy"],
    "户籍": ["hukou", "migration", "rural-urban"],
    "农村": ["rural", "agriculture", "rural-urban", "village"],
    "贸易": ["trade", "international trade", "tariff", "globalization"],
    "全球化": ["globalization", "international trade", "global"],
    "产业": ["industry", "industrial", "manufacturing", "industrial policy"],
    "产业政策": ["industrial policy", "industrial", "government intervention"],
    "金融": ["finance", "financial", "financial market", "credit"],
    "银行": ["bank", "banking", "credit", "financial institution"],
    "企业": ["firm", "firms", "corporate", "business", "enterprise"],
    "中小企业": ["small business", "sme", "entrepreneurship", "firm"],
    "创业": ["entrepreneurship", "startup", "small business", "innovation"],
    "增长": ["growth", "economic growth", "development"],
    "发展": ["development", "economic development", "growth"],
    "经济": ["economy", "economic", "economics", "economic policy"],
    "机器学习": ["machine learning", "deep learning", "artificial intelligence"],
    "大数据": ["big data", "data", "administrative data"],
    "随机实验": ["randomized experiment", "randomized controlled trial"],
    "自然实验": ["natural experiment", "quasi-experimental", "causal inference"],
}


def decompose_chinese_query(query: str) -> List[str]:
    """将中文查询拆解为英文关键词列表。"""
    if not query or not query.strip():
        return []
    query = query.strip()
    keywords: List[str] = []
    matched_indices: set = set()
    sorted_terms = sorted(CHINESE_TO_ENGLISH.keys(), key=len, reverse=True)
    for term in sorted_terms:
        if term in query:
            idx = query.index(term)
            overlap = any(mi in matched_indices for mi in range(idx, idx + len(term)))
            if not overlap:
                for mi in range(idx, idx + len(term)):
                    matched_indices.add(mi)
                keywords.extend(CHINESE_TO_ENGLISH[term])
    seen: set = set()
    deduped: List[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            deduped.append(kw)
    causal_indicators = ["因果", "影响", "评估", "效果", "实证"]
    if any(ind in query for ind in causal_indicators):
        for kw in ["causal inference", "causal", "empirical", "identification", "causality"]:
            if kw not in seen:
                deduped.append(kw)
                seen.add(kw)
    return deduped


def score_one_paper_custom(paper: Paper, custom_keywords: List[str], weight: float = 2.0) -> Paper:
    """用自定义英文关键词对论文额外加权评分。"""
    full_text = f"{paper.title} {paper.abstract} {paper.programs}".lower()
    extra_score = 0
    matched_kws: List[str] = []
    for kw in custom_keywords:
        kw_lower = kw.lower()
        pattern = r"\b" + re.escape(kw_lower) + r"\b" if re.match(r"^[a-z0-9\- ]+$", kw_lower) else re.escape(kw_lower)
        if re.search(pattern, full_text):
            extra_score += weight
            if kw not in matched_kws:
                matched_kws.append(kw)
    if extra_score == 0:
        return dataclasses.replace(paper, _matched_kws=matched_kws)
    old_highlights = list(paper.highlights)
    old_highlights.insert(0, f"自定义+{int(extra_score)}分")
    new_highlights = tuple(old_highlights[:3])
    new_score = min(100, paper.score + int(extra_score))
    new_level = "A" if new_score >= 70 else "B" if new_score >= 50 else "C" if new_score >= 35 else "D"
    if paper.score == 0:
        matched_topic_str = ", ".join(matched_kws[:3])
        new_reason = f"匹配自定义搜索关键词：{matched_topic_str}，建议人工复核。"
    else:
        new_reason = f"{paper.reason}（同时匹配自定义搜索主题，额外+{int(extra_score)}分）"
    return dataclasses.replace(
        paper, score=new_score, level=new_level,
        reason=new_reason, highlights=new_highlights,
        _matched_kws=matched_kws,
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_nber_id(text: str) -> str:
    if not text:
        return ""
    match = re.search(r"\b([wht]\d{4,6})\b", text, flags=re.I)
    return match.group(1).lower() if match else ""


def normalize_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        parsed = dt.datetime(*value[:6]) if isinstance(value, tuple) else None
    except Exception:
        parsed = None
    if parsed:
        return parsed.date().isoformat()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            pass
    return text


def fetch_tsv(filename: str) -> pd.DataFrame:
    """Fetch a TSV file from the NBER metadata repository."""
    url = f"{METADATA_BASE}/{filename}"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), sep="\t", dtype=str, engine="python", on_bad_lines="skip")


def fetch_nber_papers(max_papers: int = 50) -> List[Paper]:
    """Fetch recent NBER working papers from the public TSV metadata repository.

    Downloads ref.tsv (paper, author, title, issue_date, doi),
    abs.tsv (paper, abstract), and prog.tsv (paper, program), then merges
    them by paper ID and filters to the most recent papers.
    """
    cutoff = (dt.date.today() - dt.timedelta(weeks=METADATA_WEEKS)).isoformat()

    ref = fetch_tsv("ref.tsv")
    ref = ref[ref["paper"].str.match(r"^w\d{4,5}$", na=False)].copy()
    ref["issue_date"] = pd.to_datetime(ref["issue_date"], errors="coerce")
    ref = ref[ref["issue_date"].notna()]
    ref = ref[ref["issue_date"] >= cutoff].copy()
    ref = ref.sort_values("issue_date", ascending=False).head(max_papers)

    abs_df = fetch_tsv("abs.tsv")
    prog = fetch_tsv("prog.tsv")

    prog_grouped = (
        prog.groupby("paper")["program"]
        .apply(lambda codes: ", ".join(dict.fromkeys(PROGRAM_CODES.get(c, c) for c in codes)))
        .reset_index()
    )

    merged = ref.merge(abs_df, on="paper", how="left")
    merged = merged.merge(prog_grouped, on="paper", how="left")

    papers: List[Paper] = []
    for _, row in merged.iterrows():
        nber_id = clean_text(row.get("paper", ""))
        title = clean_text(row.get("title", ""))
        authors = clean_text(row.get("author", ""))
        abstract = clean_text(row.get("abstract", "") or "")
        published = row["issue_date"].strftime("%Y-%m-%d") if pd.notna(row.get("issue_date")) else ""
        programs = clean_text(row.get("program", ""))
        url = f"https://www.nber.org/papers/{nber_id}"
        papers.append(Paper(
            nber_id=nber_id, title=title, authors=authors,
            abstract=abstract, url=url, published=published,
            programs=programs,
        ))

    return papers


def keyword_hits(text: str, keywords: Sequence[str]) -> List[str]:
    lower = text.lower()
    hits = []
    for kw in keywords:
        pattern = r"\b" + re.escape(kw.lower()) + r"\b" if re.match(r"^[a-z0-9\- ]+$", kw.lower()) else re.escape(kw.lower())
        if re.search(pattern, lower):
            hits.append(kw)
    return hits


def score_one_paper(paper: Paper) -> Paper:
    title_text = paper.title.lower()
    full_text = f"{paper.title} {paper.abstract} {paper.programs}".lower()
    topic_scores: List[Tuple[str, int, int]] = []

    for topic, spec in TOPIC_KEYWORDS.items():
        hits = keyword_hits(full_text, spec["keywords"])
        title_hits = keyword_hits(title_text, spec["keywords"])
        if hits or title_hits:
            score = len(hits) * 6 + len(title_hits) * 8
            topic_scores.append((topic, score, len(hits)))

    program_score = 0
    for program, boost in PROGRAM_HINTS.items():
        if program.lower() in full_text:
            program_score += boost

    method_score = 0
    method_highlights: List[str] = []
    for label, kws in METHOD_KEYWORDS.items():
        hits = keyword_hits(full_text, kws)
        if hits:
            method_score += min(12, len(hits) * 3)
            method_highlights.append(label)

    base_score = sum(score for _, score, _ in topic_scores[:6])
    total = min(100, base_score + program_score + method_score)

    topic_scores_sorted = sorted(topic_scores, key=lambda x: x[1], reverse=True)
    matched_topics = [x[0] for x in topic_scores_sorted]
    highlights: List[str] = []
    for topic in matched_topics:
        highlight = TOPIC_KEYWORDS[topic]["highlight"]
        if highlight not in highlights:
            highlights.append(highlight)
    for label in method_highlights:
        if label not in highlights:
            highlights.append(label)
    for fallback in GENERAL_FALLBACK_HIGHLIGHTS:
        if fallback not in highlights:
            highlights.append(fallback)
    highlights = [h[:10] for h in highlights[:3]]

    level = "A" if total >= 70 else "B" if total >= 50 else "C" if total >= 35 else "D"
    if matched_topics:
        reason = f"涉及{matched_topics[0]}，适合公共经济与管理跟踪。"
    elif total >= 35:
        reason = "与公共政策或实证评估存在关联。"
    else:
        reason = "相关性偏弱，建议人工复核。"

    return dataclasses.replace(
        paper,
        score=int(total),
        level=level,
        reason=reason,
        highlights=tuple(highlights[:3]),
        matched_topics=tuple(matched_topics[:5]),
    )


def score_papers(papers: Iterable[Paper], min_score: int = 35) -> List[Paper]:
    scored = [score_one_paper(p) for p in papers]
    scored = [p for p in scored if p.score >= min_score]
    return sorted(scored, key=lambda p: (p.score, p.published), reverse=True)


def papers_to_dataframe(papers: Sequence[Paper]) -> pd.DataFrame:
    rows = []
    for p in papers:
        rows.append({
            "level": p.level,
            "score": p.score,
            "nber_id": p.nber_id,
            "title": p.title,
            "authors": p.authors,
            "published": p.published,
            "programs": p.programs,
            "reason": p.reason,
            "highlight_1": p.highlights[0],
            "highlight_2": p.highlights[1],
            "highlight_3": p.highlights[2],
            "topics": ", ".join(p.matched_topics),
            "url": p.url,
        })
    return pd.DataFrame(rows)


def render_markdown_digest(papers: Sequence[Paper], title: str = "NBER Public Econ Radar") -> str:
    today = dt.date.today().isoformat()
    lines = [f"# {title}", "", f"生成日期：{today}", "", f"筛选结果：{len(papers)} 篇", ""]
    for i, p in enumerate(papers, 1):
        lines.extend([
            f"## {i}. {p.title}", "",
            f"- 等级：{p.level}",
            f"- 相关性：{p.score}/100",
            f"- 作者：{p.authors or 'N/A'}",
            f"- NBER编号：{p.nber_id or 'N/A'}",
            f"- 日期：{p.published or 'N/A'}",
            f"- 方向：{', '.join(p.matched_topics) or p.programs or '待复核'}",
            f"- 一句话：{p.reason}",
            "- Highlights：",
            f"  - {p.highlights[0]}",
            f"  - {p.highlights[1]}",
            f"  - {p.highlights[2]}",
            f"- 链接：{p.url}",
            "",
            "---",
            "",
        ])
    return "\n".join(lines)


def init_db(db_path: str = "nber_radar.sqlite") -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nber_id TEXT,
            title TEXT,
            url TEXT,
            action TEXT,
            note TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def save_feedback(paper: Paper, action: str, note: str = "", db_path: str = "nber_radar.sqlite") -> None:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO feedback (nber_id, title, url, action, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (paper.nber_id, paper.title, paper.url, action, note, dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def list_feedback(db_path: str = "nber_radar.sqlite") -> pd.DataFrame:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM feedback ORDER BY created_at DESC", conn)
    conn.close()
    return df


def send_email_digest(markdown_body: str, subject: str = "NBER Public Econ Radar") -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", user or "")
    recipient = os.getenv("EMAIL_TO")
    if not all([host, user, password, sender, recipient]):
        raise RuntimeError("邮件推送需要设置 SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO。")

    msg = MIMEText(markdown_body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(sender, [recipient], msg.as_string())


def save_outputs(papers: Sequence[Paper], out_dir: str = "output") -> Tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    df = papers_to_dataframe(papers)
    csv_path = out / f"nber_public_econ_{today}.csv"
    md_path = out / f"nber_public_econ_{today}.md"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    md_path.write_text(render_markdown_digest(papers), encoding="utf-8")
    return csv_path, md_path
