import argparse

from nber_radar import fetch_nber_papers, render_markdown_digest, save_outputs, score_papers, send_email_digest


def main():
    parser = argparse.ArgumentParser(description="NBER Public Econ Radar weekly digest")
    parser.add_argument("--max-papers", type=int, default=50)
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--out-dir", default="output")
    parser.add_argument("--send-email", action="store_true")
    args = parser.parse_args()

    raw = fetch_nber_papers(max_papers=args.max_papers)
    papers = score_papers(raw, min_score=args.min_score)
    csv_path, md_path = save_outputs(papers, out_dir=args.out_dir)
    print(f"筛选出 {len(papers)} 篇")
    print(f"CSV: {csv_path}")
    print(f"Markdown: {md_path}")

    if args.send_email:
        body = render_markdown_digest(papers)
        send_email_digest(body)
        print("邮件已发送")


if __name__ == "__main__":
    main()
