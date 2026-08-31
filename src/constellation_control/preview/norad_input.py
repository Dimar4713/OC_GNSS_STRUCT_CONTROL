from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.norad import preview_norad_import


class NoradPreviewRequest(BaseModel):
    filename: str
    content_text: str


NORAD_CARD = r"""
<div class="card" id="noradCard">
  <h3>NORAD TLE / OMM</h3>
  <p class="hint">Импорт здесь только валидирует и нормализует NORAD/SGP4 mean elements. Они не считаются ни осциллирующими Кеплеровыми, ни canonical mean elements проекта. Создание runnable scenario блокируется до отдельного Orekit TLE/SGP4 authority шага.</p>
  <input id="noradFile" type="file" accept=".tle,.txt,.json">
  <button onclick="previewNorad()">Проверить NORAD файл / Preview NORAD file</button>
  <pre id="noradPreview"></pre>
  <div id="noradStatus" class="status"></div>
</div>
"""

NORAD_SCRIPT = r"""
async function previewNorad(){
 const input=document.getElementById('noradFile');
 const file=input.files&&input.files[0];
 if(!file){noradStatus.textContent='Выберите .tle/.txt или OMM .json';noradStatus.className='status danger';return;}
 const text=await file.text();
 noradStatus.textContent='Validation…';
 const r=await fetch('/api/norad/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,content_text:text})});
 const d=await r.json();
 if(!r.ok){noradStatus.textContent=d.detail||'NORAD preview failed';noradStatus.className='status danger';return;}
 noradPreview.textContent=JSON.stringify(d,null,2);
 noradStatus.textContent='VALID: records='+d.records.length+'; runnable promotion='+d.runnable_promotion_allowed;
 noradStatus.className='status ok';
}
"""


def install_norad_routes(app: FastAPI) -> None:
    @app.post('/api/norad/preview')
    def preview(request: NoradPreviewRequest) -> dict[str, object]:
        try:
            return preview_norad_import(request.filename, request.content_text).model_dump(mode='json')
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
