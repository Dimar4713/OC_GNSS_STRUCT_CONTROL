from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from constellation_control.adapters.gnss_almanac import GnssAlmanacFormat, preview_gnss_almanac


class GnssAlmanacPreviewRequest(BaseModel):
    filename: str
    content_text: str
    source_format: GnssAlmanacFormat


GNSS_ALMANAC_CARD = r"""
<div class="card" id="gnssAlmanacCard">
  <h3>GNSS Almanac intake</h3>
  <p class="hint">YUMA/SEM и GLONASS labelled almanac импортируются только как reduced-precision almanac input. Они не переименовываются в canonical MeanOrbit и пока не создают runnable scenario.</p>
  <div class="grid">
    <label>Формат / Format
      <select id="gnssAlmanacFormat">
        <option value="gps-yuma">GPS YUMA</option>
        <option value="gps-sem">GPS SEM</option>
        <option value="glonass-text">GLONASS labelled text</option>
      </select>
    </label>
    <label>Файл / File <input id="gnssAlmanacFile" type="file" accept=".alm,.al3,.txt"></label>
  </div>
  <button onclick="previewGnssAlmanac()">Проверить альманах / Preview almanac</button>
  <div id="gnssAlmanacStatus" class="status"></div>
  <pre id="gnssAlmanacPreview"></pre>
</div>
"""

GNSS_ALMANAC_SCRIPT = r"""
async function previewGnssAlmanac(){
 const file=gnssAlmanacFile.files&&gnssAlmanacFile.files[0];
 if(!file){gnssAlmanacStatus.textContent='Выберите файл альманаха';gnssAlmanacStatus.className='status danger';return;}
 const text=await file.text();gnssAlmanacStatus.textContent='Validation…';
 const r=await fetch('/api/gnss-almanac/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({filename:file.name,content_text:text,source_format:gnssAlmanacFormat.value})});
 const d=await r.json();
 if(!r.ok){gnssAlmanacStatus.textContent=d.detail||'Almanac preview failed';gnssAlmanacStatus.className='status danger';return;}
 gnssAlmanacPreview.textContent=JSON.stringify(d,null,2);
 gnssAlmanacStatus.textContent='VALID: '+d.source_format+'; records='+d.records.length+'; runnable='+d.runnable_promotion_allowed;
 gnssAlmanacStatus.className='status ok';
}
"""


def install_gnss_almanac_routes(app: FastAPI) -> None:
    @app.post("/api/gnss-almanac/preview")
    def preview(request: GnssAlmanacPreviewRequest) -> dict[str, object]:
        try:
            return preview_gnss_almanac(
                request.filename,
                request.content_text,
                request.source_format,
            ).model_dump(mode="json")
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
