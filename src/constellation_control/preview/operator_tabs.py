from __future__ import annotations

OPERATOR_TABS_CARD = r"""
<div class="card active-run-card" id="activeRunConfigurationCard">
  <h3>Активная расчётная конфигурация / Active Run Configuration</h3>
  <p class="hint">Перед запуском здесь всегда показана точная комбинация входов. Смена вкладки не меняет расчётные входы скрыто. / The exact input combination is always shown here before execution. Changing tabs never changes run inputs implicitly.</p>
  <div class="active-run-grid">
    <div><b>Runnable Scenario</b><div id="activeScenario">—</div></div>
    <div><b>Mode / Режим</b><div id="activeMode">—</div></div>
    <div><b>Force model</b><div id="activeForceModel">—</div></div>
    <div><b>Authority</b><div id="activeAuthority">—</div></div>
    <div><b>Design screening</b><div id="activeDesignScreening">—</div></div>
    <div><b>Design validation</b><div id="activeDesignValidation">—</div></div>
    <div><b>Design config</b><div id="activeDesignConfig">—</div></div>
    <div><b>Robustness validation</b><div id="activeRobustnessValidation">—</div></div>
    <div><b>Robustness config</b><div id="activeRobustnessConfig">—</div></div>
    <div><b>Force fingerprint</b><div><code id="activeFingerprint">—</code></div></div>
  </div>
  <div id="activeRunSummary" class="status">Загрузите ScenarioConfig / Load a ScenarioConfig.</div>
</div>
<nav class="operator-tabs" id="operatorTabs" aria-label="Operator workspace tabs">
  <button type="button" data-tab="scenarios" onclick="showOperatorTab('scenarios')">Сценарии / Scenarios</button>
  <button type="button" data-tab="inputs" onclick="showOperatorTab('inputs')">Входные данные и импорт / Inputs & Import</button>
  <button type="button" data-tab="design" onclick="showOperatorTab('design')">Design / Проектирование</button>
  <button type="button" data-tab="robustness" onclick="showOperatorTab('robustness')">Robustness / Робастность</button>
  <button type="button" data-tab="results" onclick="showOperatorTab('results')">Результаты / Results</button>
  <button type="button" data-tab="expert" onclick="showOperatorTab('expert')">Эксперт / Expert</button>
</nav>
<div id="operatorTabScenarios" class="operator-tab-pane" data-tab-pane="scenarios"></div>
<div id="operatorTabInputs" class="operator-tab-pane" data-tab-pane="inputs"></div>
<div id="operatorTabDesign" class="operator-tab-pane" data-tab-pane="design"></div>
<div id="operatorTabRobustness" class="operator-tab-pane" data-tab-pane="robustness"></div>
<div id="operatorTabResults" class="operator-tab-pane" data-tab-pane="results"></div>
<div id="operatorTabExpert" class="operator-tab-pane" data-tab-pane="expert"></div>
"""

OPERATOR_TABS_STYLE = r"""
<style id="operatorTabsStyle">
.operator-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px 0;position:sticky;top:0;z-index:10;background:#f4f6f8;padding:8px 0}
.operator-tabs button{width:auto;margin:0;padding:9px 13px;border:1px solid #cbd3da;border-radius:7px;background:white}
.operator-tabs button.active{font-weight:700;outline:2px solid #17202a}
.operator-tab-pane{display:none}.operator-tab-pane.active{display:block}
.active-run-card{border-width:2px}.active-run-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 18px}
.active-run-grid>div{min-width:0}.active-run-grid code{word-break:break-all;font-size:11px}
.workflow-split-card{border-left:4px solid #d9dee3}
@media(max-width:900px){.active-run-grid{grid-template-columns:1fr}.operator-tabs{position:static}}
</style>
"""

OPERATOR_TABS_SCRIPT = r"""
function operatorById(id){return document.getElementById(id);}
function operatorText(id,value){const e=operatorById(id);if(e)e.textContent=(value===undefined||value===null||value==='')?'—':String(value);}
function operatorSelectValue(id){const e=operatorById(id);return e&&e.value?e.value:'—';}
function activeRunRefresh(){
  const selected=operatorSelectValue('scenario');
  const normalized=(window.current&&current.normalized)||{};
  const force=normalized.force_model||{};
  operatorText('activeScenario',selected);
  operatorText('activeMode',current&&current.force_mode?current.force_mode:(force.mode||'—'));
  operatorText('activeForceModel',force.gravity_model?force.gravity_model+' '+force.gravity_degree+'x'+force.gravity_order:'—');
  operatorText('activeAuthority',current&&current.authority?current.authority:'—');
  operatorText('activeFingerprint',current&&current.force_model_fingerprint?current.force_model_fingerprint:'—');
  operatorText('activeDesignScreening',operatorSelectValue('designScreening'));
  operatorText('activeDesignValidation',operatorSelectValue('designValidation'));
  operatorText('activeDesignConfig',operatorSelectValue('designConfig'));
  operatorText('activeRobustnessValidation',operatorSelectValue('robustnessValidation'));
  operatorText('activeRobustnessConfig',operatorSelectValue('robustnessConfig'));
  const summary=operatorById('activeRunSummary');
  if(summary){
    const tab=localStorage.getItem('operator-tab')||'scenarios';
    if(tab==='design')summary.textContent='DESIGN: screening='+operatorSelectValue('designScreening')+' + validation='+operatorSelectValue('designValidation')+' + config='+operatorSelectValue('designConfig');
    else if(tab==='robustness')summary.textContent='ROBUSTNESS: validation='+operatorSelectValue('robustnessValidation')+' + config='+operatorSelectValue('robustnessConfig');
    else summary.textContent='SCENARIO RUN: '+selected+'; mode='+(current&&current.force_mode?current.force_mode:'—')+'; authority='+(current&&current.authority?current.authority:'—');
  }
}
function operatorMoveCard(id,target){const card=operatorById(id),pane=operatorById(target);if(card&&pane)pane.appendChild(card);}
function splitWorkflowCard(){
  const card=operatorById('workflowCard');if(!card)return;
  const nodes=Array.from(card.childNodes);let robust=false;
  const design=document.createElement('div');design.className='card workflow-split-card';design.id='designWorkflowCard';
  const robustness=document.createElement('div');robustness.className='card workflow-split-card';robustness.id='robustnessWorkflowCard';
  for(const node of nodes){
    if(node.nodeType===1&&node.tagName==='H4'&&String(node.textContent).includes('Robustness'))robust=true;
    (robust?robustness:design).appendChild(node);
  }
  card.replaceWith(design,robustness);
}
function arrangeOperatorTabs(){
  const section=document.querySelector('main section');if(!section)return;
  splitWorkflowCard();
  const panes=['operatorTabScenarios','operatorTabInputs','operatorTabDesign','operatorTabRobustness','operatorTabResults','operatorTabExpert'];
  for(const p of panes){const pane=operatorById(p);if(pane&&pane.parentElement!==section)section.appendChild(pane);}
  const unassigned=Array.from(section.children).filter(x=>x.classList&&x.classList.contains('card')&&!x.id);
  if(unassigned[0])operatorById('operatorTabScenarios').appendChild(unassigned[0]);
  if(unassigned[1])operatorById('operatorTabScenarios').appendChild(unassigned[1]);
  if(unassigned[2])operatorById('operatorTabScenarios').appendChild(unassigned[2]);
  if(unassigned[3])operatorById('operatorTabResults').appendChild(unassigned[3]);
  if(unassigned[4])operatorById('operatorTabExpert').appendChild(unassigned[4]);
  if(unassigned[5])operatorById('operatorTabExpert').appendChild(unassigned[5]);
  ['scenarioEditorCard','gravityModelCard','constellationEditorCard','perturbationCard','spacecraftCatalogCard','resourceStateCard'].forEach(id=>operatorMoveCard(id,'operatorTabScenarios'));
  ['galileoGscCard','iacGnssCard','glonassAlmanacCard','gnssAlmanacCard','noradCard','osculatingCard','walkerCard','workbookCard'].forEach(id=>operatorMoveCard(id,'operatorTabInputs'));
  ['designWorkflowCard','optimalOperationsCard'].forEach(id=>operatorMoveCard(id,'operatorTabDesign'));
  ['robustnessWorkflowCard'].forEach(id=>operatorMoveCard(id,'operatorTabRobustness'));
  ['runPromotionCard','driftConsistencyCard'].forEach(id=>operatorMoveCard(id,'operatorTabResults'));
  ['scenarioEditorCard'].forEach(()=>{});
  const active=localStorage.getItem('operator-tab')||'scenarios';showOperatorTab(active);
}
function showOperatorTab(name){
  document.querySelectorAll('[data-tab-pane]').forEach(p=>p.classList.toggle('active',p.dataset.tabPane===name));
  document.querySelectorAll('#operatorTabs [data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  localStorage.setItem('operator-tab',name);activeRunRefresh();
}
function installActiveRunListeners(){
  ['scenario','designScreening','designValidation','designConfig','robustnessValidation','robustnessConfig'].forEach(id=>{const e=operatorById(id);if(e)e.addEventListener('change',activeRunRefresh);});
}
const operatorOriginalLoadScenario=loadScenario;
loadScenario=async function(){await operatorOriginalLoadScenario();activeRunRefresh();};
const operatorTabsBootstrap=bootstrap;
bootstrap=async function(){await operatorTabsBootstrap();arrangeOperatorTabs();installActiveRunListeners();activeRunRefresh();};
"""
