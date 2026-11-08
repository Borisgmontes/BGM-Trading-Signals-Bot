(() => {
  const API = 'https://bgm-quant-lab-api.onrender.com';
  const STORE = 'bgmQuantLab.strategyLibrary.v3';
  const $ = (id) => document.getElementById(id);
  const features = [
    ['close','Precio de cierre'],['ema_10','EMA 10'],['ema_20','EMA 20'],['ema_50','EMA 50'],['ema_100','EMA 100'],['ema_200','EMA 200'],
    ['rsi_14','RSI 14'],['atr_14','ATR 14'],['macd_hist','MACD histograma'],['volume_ratio','Volumen relativo'],['bb_upper','Bollinger superior'],['bb_lower','Bollinger inferior'],
    ['ema_10_cross_up_ema_20','Cruce alcista EMA 10/20'],['ema_10_cross_down_ema_20','Cruce bajista EMA 10/20'],
    ['ema_20_cross_up_ema_50','Cruce alcista EMA 20/50'],['ema_20_cross_down_ema_50','Cruce bajista EMA 20/50'],
    ['ema_50_cross_up_ema_200','Cruce alcista EMA 50/200'],['ema_50_cross_down_ema_200','Cruce bajista EMA 50/200'],
    ['session_asia_open','Apertura Tokio'],['session_london_open','Apertura Londres'],['session_new_york_open','Apertura Nueva York']
  ];
  const groups = [
    ['long','Entrada LONG'],['short','Entrada SHORT'],['longExit','Salida LONG'],['shortExit','Salida SHORT']
  ];
  const state = { rules: {long:[],short:[],longExit:[],shortExit:[]}, active: null, last: null };
  const esc = (v) => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const load = () => { try { const x=JSON.parse(localStorage.getItem(STORE)||'[]'); return Array.isArray(x)?x:[]; } catch { return []; } };
  const save = (items) => localStorage.setItem(STORE,JSON.stringify(items));
  const featureOptions = () => features.map(([v,l])=>'<option value="'+v+'">'+l+'</option>').join('');
  function mount(){
    const host=document.createElement('section'); host.className='panel'; host.id='visualBuilder';
    host.innerHTML='<div class="head"><h2>08 / Constructor visual de reglas</h2><span class="pill">Indicadores + eventos</span></div>'+
      '<p class="hint">Combina reglas escritas con condiciones seleccionadas. Cada cruce es un evento de una sola vela. Las aperturas usan la zona horaria local de cada mercado y respetan el horario de verano; requieren velas que coincidan con la hora de apertura.</p>'+
      '<div class="sectionlabel">ENTRADAS</div><div id="entryRules" class="grid" style="grid-template-columns:1fr 1fr;gap:10px"></div>'+
      '<div class="sectionlabel">SALIDAS POR CONDICIÓN</div><div id="exitRules" class="grid" style="grid-template-columns:1fr 1fr;gap:10px"></div>'+
      '<div class="btnrow"><button class="btn secondary" id="importNatural" type="button">Combinar reglas del texto</button><button class="btn secondary" id="resetVisual" type="button">Limpiar reglas visuales</button><button class="btn" id="saveVisual" type="button">Guardar en biblioteca</button><button class="btn" id="runVisual" type="button">Ejecutar backtest</button></div>'+
      '<div class="statusline" id="visualStatus">Añade condiciones de entrada LONG y SHORT. Las salidas son opcionales.</div>'+
      '<div id="visualResult" class="rules" hidden></div>'+
      '<div class="sectionlabel">BIBLIOTECA DE ESTRATEGIAS</div><div id="visualLibrary" class="library"></div>';
    const right=document.querySelector('.right'); right.append(host);
    groups.forEach(([key,label])=>{
      const box=document.createElement('div'); box.className='panel'; box.style.padding='12px';
      box.innerHTML='<div class="head"><h2>'+label+'</h2><button type="button" class="btn secondary" data-add="'+key+'">+ Regla</button></div><div id="rules-'+key+'" class="grid" style="gap:7px"></div>';
      (key==='long'||key==='short'?$('entryRules'):$('exitRules')).append(box);
    });
    host.querySelectorAll('[data-add]').forEach(b=>b.addEventListener('click',()=>addRule(b.dataset.add)));
    $('importNatural').addEventListener('click',importNatural);
    $('resetVisual').addEventListener('click',()=>{Object.keys(state.rules).forEach(k=>state.rules[k]=[]);renderRules();status('Reglas visuales eliminadas.');});
    $('saveVisual').addEventListener('click',saveStrategy);
    $('runVisual').addEventListener('click',runBacktest);
    renderRules(); renderLibrary();
  }
  function addRule(group,rule={feature:'ema_10_cross_up_ema_20',operator:'>',value:0.5}){
    state.rules[group].push({...rule}); renderRules();
  }
  function renderRules(){
    groups.forEach(([group])=>{
      const box=$('rules-'+group); box.innerHTML='';
      state.rules[group].forEach((r,i)=>{
        const row=document.createElement('div'); row.style.cssText='display:grid;grid-template-columns:minmax(0,1.5fr) 65px minmax(70px,1fr) 32px;gap:5px;align-items:center';
        const select=document.createElement('select'); select.innerHTML=featureOptions(); select.value=r.feature;
        const op=document.createElement('select'); op.innerHTML=['>','<','>=','<='].map(x=>'<option>'+x+'</option>').join(''); op.value=r.operator;
        const val=document.createElement('input'); val.type='number'; val.step='any'; val.value=r.value; val.title='Valor de comparación';
        const del=document.createElement('button'); del.type='button'; del.className='btn secondary'; del.textContent='×'; del.title='Eliminar regla';
        select.addEventListener('change',()=>{r.feature=select.value;if(r.feature.startsWith('ema_')&&r.feature.includes('_cross_')){r.operator='>';r.value=0.5;renderRules()}});
        op.addEventListener('change',()=>r.operator=op.value); val.addEventListener('change',()=>r.value=Number(val.value));
        del.addEventListener('click',()=>{state.rules[group].splice(i,1);renderRules()});
        row.append(select,op,val,del); box.append(row);
      });
      if(!state.rules[group].length){const p=document.createElement('div');p.className='empty';p.textContent='Sin condiciones';box.append(p)}
    });
  }
  function status(msg,bad=false){$('visualStatus').textContent=msg;$('visualStatus').className='statusline '+(bad?'warning':'ok')}
  function currentStrategy(){
    const read=(key)=>state.rules[key].map(r=>({feature:r.feature,operator:r.operator,value:Number(r.value)}));
    const long=read('long'),short=read('short');
    if(!long.length||!short.length)throw Error('Define al menos una condición de entrada LONG y una SHORT.');
    const name=$('strategyName').value.trim();if(!name)throw Error('Escribe un nombre para la estrategia.');
    return {name,long_conditions:long,short_conditions:short,long_exit_conditions:read('longExit'),short_exit_conditions:read('shortExit'),
      stop_atr:Number($('stopAtr').value),reward_risk:Number($('rewardRisk').value),risk_per_trade_pct:Number($('riskPct').value),max_holding_bars:Number($('maxHolding').value)};
  }
  async function importNatural(){
    try{
      const description=$('description').value.trim();if(!description)throw Error('Escribe primero una descripción.');
      const res=await fetch(API+'/api/interpret',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description,name:$('strategyName').value})});
      const data=await res.json();if(!res.ok||!data.ok)throw Error(data.error||'No se pudo interpretar el texto.');
      const s=data.strategy;
      ['long','short'].forEach(k=>{state.rules[k].push(...s[k+'_conditions']);});
      renderRules();status('Reglas del texto combinadas con el constructor visual. Comprueba posibles duplicados.');
    }catch(e){status(e.message,true)}
  }
  function config(){
    return {market:'BTCUSDT',timeframe:$('timeframe').value,candles:Number($('candles').value),initial_equity:Number($('initialEquity').value),
      fee_bps:Number($('feeBps').value),slippage_bps:Number($('slippageBps').value),strategy:currentStrategy()};
  }
  function saveStrategy(){
    try{
      const payload=config(),items=load(),id=state.active||('visual-'+Date.now());
      const old=items.find(x=>x.id===id);
      const item={id,name:payload.strategy.name,saved_at:old?.saved_at||new Date().toISOString(),strategy:payload.strategy,
        config:{timeframe:payload.timeframe,candles:payload.candles,initial_equity:payload.initial_equity,fee_bps:payload.fee_bps,slippage_bps:payload.slippage_bps},
        last_result:old?.last_result||null};
      const next=[item,...items.filter(x=>x.id!==id)];save(next);state.active=id;renderLibrary();status('Estrategia guardada en la biblioteca de este navegador.');
    }catch(e){status(e.message,true)}
  }
  function renderLibrary(){
    const box=$('visualLibrary');if(!box)return;const items=load();box.innerHTML='';
    if(!items.length){box.innerHTML='<div class="empty">No hay estrategias guardadas todavía.</div>';return}
    items.forEach(item=>{
      const row=document.createElement('div');row.className='saved';
      const info=document.createElement('div'),name=document.createElement('b'),meta=document.createElement('small');
      name.textContent=item.name;meta.textContent=(item.config.timeframe||'5m')+' · '+(item.last_result?'Último OOS: '+Number(item.last_result.net_return_pct).toFixed(2)+'%':'Sin backtest');
      if(item.last_result){name.style.color=item.last_result.net_return_pct>0?'#80a8ff':item.last_result.net_return_pct<0?'#f07886':'#aab5c5'}
      info.append(name,meta);const actions=document.createElement('div');actions.className='btnrow';
      const use=document.createElement('button');use.className='btn secondary';use.textContent='Cargar';use.addEventListener('click',()=>loadStrategy(item.id));
      const del=document.createElement('button');del.className='btn secondary';del.textContent='Eliminar';del.addEventListener('click',()=>{save(load().filter(x=>x.id!==item.id));renderLibrary()});
      actions.append(use,del);row.append(info,actions);box.append(row);
    });
  }
  function loadStrategy(id){
    const item=load().find(x=>x.id===id);if(!item)return;state.active=id;
    $('strategyName').value=item.name;$('timeframe').value=item.config.timeframe;$('candles').value=String(item.config.candles);
    $('initialEquity').value=item.config.initial_equity;$('feeBps').value=item.config.fee_bps;$('slippageBps').value=item.config.slippage_bps;
    $('stopAtr').value=item.strategy.stop_atr;$('rewardRisk').value=item.strategy.reward_risk;$('riskPct').value=item.strategy.risk_per_trade_pct;$('maxHolding').value=item.strategy.max_holding_bars;
    state.rules.long=item.strategy.long_conditions||[];state.rules.short=item.strategy.short_conditions||[];
    state.rules.longExit=item.strategy.long_exit_conditions||[];state.rules.shortExit=item.strategy.short_exit_conditions||[];
    renderRules();status('Estrategia cargada desde la biblioteca.');if(item.last_result)showResult(item.last_result);
  }
  function showResult(r){
    const box=$('visualResult');box.hidden=false;
    const cls=r.net_return_pct>0?'positive':r.net_return_pct<0?'negative':'';
    box.innerHTML='<strong>Resultado OUT-OF-SAMPLE</strong><div class="'+cls+'">Retorno neto: '+Number(r.net_return_pct).toFixed(2)+'% · Win rate: '+Number(r.win_rate_pct).toFixed(1)+'% · Profit factor: '+(r.profit_factor==null?'N/D':Number(r.profit_factor).toFixed(2))+' · Operaciones: '+r.trades+' · Drawdown: '+Number(r.max_drawdown_pct).toFixed(2)+'%</div>';
  }
  async function runBacktest(){
    let payload;try{payload=config()}catch(e){status(e.message,true);return}
    const button=$('runVisual');button.disabled=true;status('Descargando velas reales y ejecutando backtest…');
    try{
      const res=await fetch(API+'/api/backtest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const data=await res.json();if(!res.ok||!data.ok)throw Error(data.error||'El motor no pudo completar el backtest.');
      const oos=data.out_of_sample;showResult(oos);
      const items=load(),id=state.active||('visual-'+Date.now()),old=items.find(x=>x.id===id);
      const item={id,name:payload.strategy.name,saved_at:old?.saved_at||new Date().toISOString(),strategy:payload.strategy,
        config:{timeframe:payload.timeframe,candles:payload.candles,initial_equity:payload.initial_equity,fee_bps:payload.fee_bps,slippage_bps:payload.slippage_bps},
        last_result:{net_return_pct:oos.net_return_pct,win_rate_pct:oos.win_rate_pct,profit_factor:oos.profit_factor,trades:oos.trades,max_drawdown_pct:oos.max_drawdown_pct,data_start:data.data_start,data_end:data.data_end}};
      save([item,...items.filter(x=>x.id!==id)]);state.active=id;renderLibrary();
      status('Backtest real completado: '+data.candles_used+' velas · '+data.data_start+' a '+data.data_end+'.');
    }catch(e){status(e.message,true)}finally{button.disabled=false}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();