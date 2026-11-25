"""Print the reviewed HTML, retaining both deliverables and their binding."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from scene import load
from workflow import atomic_json, checked_html, checked_session, now


def browser_command(browser=None):
    """Resolve the printing driver: explicit path, agent-browser, or bundled shim."""
    if browser:
        return [shutil.which(browser) or browser]
    env = os.environ.get("AGENT_BROWSER_BIN")
    if env:
        return [env]
    found = shutil.which("agent-browser")
    if found:
        return [found]
    node = shutil.which("node")
    shim = Path(__file__).resolve().parent / "agent_browser_shim.mjs"
    if node and shim.is_file():
        return [node, str(shim)]
    raise ValueError(
        "缺少 agent-browser，请安装该 CLI、安装 Node.js 以使用自带打印脚本，"
        "或通过 --browser-executable / AGENT_BROWSER_BIN 指定"
    )


def export_pdf(
    session_path, context, output, browser=None, user_reply=None, draft=False
):
    state = checked_session(session_path, context)
    directory = Path(session_path).resolve().parent
    manifest, _ = load(directory / "report-manifest.json")
    html = checked_html(state, manifest, directory)
    if manifest.get("visualReviewStatus") != "accepted":
        raise ValueError("请先完成本次 HTML 的视觉复核")
    if manifest.get("status") == "draft" and not draft:
        raise ValueError("合成或不完整证据只允许导出明确标记的 PDF 草稿")
    authorization = state.get("pdfAuthorization", {})
    if user_reply is not None:
        if not isinstance(user_reply, str) or not user_reply.strip():
            raise ValueError("需要用户明确的双版本交付回复")
        authorization = {
            "actor": "user",
            "htmlSha256": manifest["htmlSha256"],
            "userReply": user_reply,
            "at": now(),
        }
    if not state["request"].get("pdf") and not (
        authorization.get("actor") == "user"
        and authorization.get("htmlSha256") == manifest["htmlSha256"]
    ):
        raise ValueError("本次仅授权 HTML，请先取得用户保留 PDF 的明确回复")
    destination = Path(output).resolve()
    if (
        not destination.is_relative_to(directory)
        or destination.suffix.lower() != ".pdf"
    ):
        raise ValueError("PDF 须保存在本次任务目录中，使用 .pdf 扩展名")
    if destination.exists():
        previous = (
            manifest
            if manifest.get("pdf") == str(destination)
            else manifest.get("previousPdf", {})
        )
        if previous.get("pdf") != str(destination) or hashlib.sha256(
            destination.read_bytes()
        ).hexdigest() != previous.get("pdfSha256"):
            raise ValueError("不能覆盖未登记或已被修改的已有 PDF")
    prefix = browser_command(browser)
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError(
            "PDF 导出需要 pypdf，请使用具备该依赖的 Python 环境"
        ) from error

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(
        prefix=".html-print-", suffix=".pdf", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temp)
    session = "fengshui-pdf-" + uuid.uuid4().hex[:12]

    def run(*args):
        try:
            completed = subprocess.run(
                [*prefix, "--session", session, *args],
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                "浏览器打印超时，请检查本次 HTML 和本机 Chrome 状态"
            ) from error
        if completed.returncode:
            raise RuntimeError(
                "浏览器导出失败：" + (completed.stderr or completed.stdout)[-1500:]
            )

    try:
        run("open", html.as_uri())
        run(
            "wait",
            "--fn",
            "document.fonts.status === 'loaded' && [...document.images].every(i => i.complete && i.naturalWidth > 0)",
        )
        run("pdf", str(temporary))
        if not temporary.read_bytes().startswith(b"%PDF-"):
            raise ValueError("浏览器未生成有效 PDF")
        reader = PdfReader(temporary)
        page_count = len(reader.pages)
        if page_count < 1 or not any(
            (page.extract_text() or "").strip() for page in reader.pages
        ):
            raise ValueError("导出 PDF 为空或缺少可读取文本")
        checked_html(state, manifest, directory)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
        subprocess.run(
            [*prefix, "--session", session, "close"], capture_output=True, timeout=30
        )
    manifest.update(
        pdf=str(destination),
        pdfSha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        pdfSourceHtmlSha256=manifest["htmlSha256"],
        pageCount=page_count,
        pdfStatus="draft" if draft or manifest["status"] == "draft" else "generated",
        pdfVisualReviewStatus="pending",
    )
    manifest.pop("pdfVisualReviewSha256", None)
    atomic_json(directory / "report-manifest.json", manifest)
    if authorization:
        state["pdfAuthorization"] = authorization
    state.update(
        pdfPath=str(destination),
        status="report_draft" if manifest["pdfStatus"] == "draft" else "pdf_generated",
    )
    atomic_json(session_path, state)
    return manifest


def finalize_pdf(session_path, context, review_path, state, manifest):
    directory = Path(session_path).resolve().parent
    checked_html(state, manifest, directory)
    pdf = Path(manifest["pdf"]).resolve()
    if (
        not pdf.is_relative_to(directory)
        or manifest.get("pdfSourceHtmlSha256") != manifest["htmlSha256"]
    ):
        raise ValueError("PDF 与本次 HTML 不一致")
    pdf_sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    review, _ = load(review_path)
    if (
        review.get("schema") != "spatial-fengshui.pdf-visual-review"
        or review.get("pdfSha256") != pdf_sha
        or manifest.get("pdfSha256") != pdf_sha
    ):
        raise ValueError("PDF 或复核记录属于旧版本")
    if (
        review.get("textCheckPassed") is not True
        or review.get("layoutPassed") is not True
    ):
        raise ValueError("PDF 中文或排版复核尚未通过")
    pages = review.get("pages", [])
    if sorted(item.get("page") for item in pages) != list(
        range(1, manifest["pageCount"] + 1)
    ):
        raise ValueError("需要渲染并复核 PDF 全部页面")
    for item in pages:
        image = (directory / item["path"]).resolve()
        if (
            not image.is_relative_to(directory)
            or not image.is_file()
            or hashlib.sha256(image.read_bytes()).hexdigest() != item.get("sha256")
        ):
            raise ValueError("PDF 页面渲染缺失或已变化")
    from workflow import digest

    atomic_json(directory / "pdf-visual-review.json", review)
    manifest.update(
        pdfVisualReviewStatus="accepted", pdfVisualReviewSha256=digest(review)
    )
    atomic_json(directory / "report-manifest.json", manifest)
    state.update(
        status="report_draft" if manifest["pdfStatus"] == "draft" else "delivered",
        pdfVisualReviewPath=str(directory / "pdf-visual-review.json"),
    )
    atomic_json(session_path, state)
    return state
