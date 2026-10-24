"""Export an offline entry-page preview without backend access or student data."""

from __future__ import annotations

import re
from pathlib import Path

from src.rehab_affect.demo2_portal import (
    render_demo2_login_html,
    render_demo2_privacy_html,
    render_demo2_register_html,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deliverables" / "20260908_platform_entry"


def export_preview() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pages = {
        "login": render_demo2_login_html(),
        "register": render_demo2_register_html(),
        "privacy": render_demo2_privacy_html(),
    }
    preview_script = r"""
const form=document.querySelector('form');
if(form)form.addEventListener('submit',event=>{event.preventDefault();const error=document.getElementById('formError');error.textContent='此文件仅供页面预览，未连接后台，也不会提交信息。实际登录请使用部署后的平台地址。';error.className='form-error visible info';});
document.querySelectorAll('[data-role]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-role]').forEach(item=>{item.setAttribute('aria-checked',String(item===button));item.tabIndex=item===button?0:-1;});document.getElementById('roleDescription').textContent=button.dataset.role==='company_admin'?'查看账号、上传任务和后台数据。':'从一节课开始，记录每个孩子的学习。';}));
const reveal=document.getElementById('showPassword');
if(reveal)reveal.addEventListener('click',()=>{const input=document.getElementById('password');const visible=input.type==='password';input.type=visible?'text':'password';reveal.setAttribute('aria-pressed',String(visible));reveal.setAttribute('aria-label',visible?'隐藏密码':'显示密码');});
"""
    for name, content in pages.items():
        content = re.sub(r"<script>.*?</script>", "", content, flags=re.S)
        for route in pages:
            content = content.replace(f"/demo2/{route}", f"{route}.html")
        content = content.replace("学校内测</span>", "界面预览</span>")
        content = content.replace("</body>", f"<script>{preview_script}</script></body>")
        (OUTPUT / f"{name}.html").write_text(content, encoding="utf-8")
    print(OUTPUT / "login.html")


if __name__ == "__main__":
    export_preview()
