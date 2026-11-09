(() => {
  const API='https://bgm-quant-lab-api.onrender.com', STORE='bgmQuantLab.strategyLibrary.v4', $=id=>document.getElementById(id);
  const timeframes=['1m','5m','15m','1h','4h','1d'], seconds={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1d':86400};
  const groups=[['long','Entrada LONG'],['short','Entrada SHORT'],['longExit','Salida LONG'],['shortExit','Salida SHORT']];
  const state={rules:{long:[],short:[],longExit:[],shortExit:[]},active:null};
  const load=()=>{try{const current=JSON.parse(localStorage.getItem(STORE)||'null');if(Array.isArray(current))return current;
    const legacy=JSON.parse(localStorage.getItem('bgmQuantLab.strategyLibrary.v3')||'[]');
    if(!Array.isArray(legacy))return [];
    const migrated=legacy.map(item=>{const tf=item.config?.timeframe||'5m';const strategy={...item.strategy,
      indicator_settings:item.strategy?.indicator_settings||{},
      long_conditions:(item.strategy?.long_conditions||[]).map(r=>({...r,timeframe:r.timeframe||tf})),
      short_conditions:(item.strategy?.short_conditions||[]).map(r=>({...r,timeframe:r.timeframe||tf})),
      long_exit_conditions:(item.strategy?.long_exit_conditions||[]).map(r=>({...r,timeframe:r.timeframe||tf})),
      short_exit_conditions:(item.strategy?.short_exit_conditions||[]).map(r=>({...r,timeframe:r.timeframe||tf}))};
      return {...item,strategy};});
    localStorage.setItem(STORE,JSON.stringify(migrated));return migrated;
    }catch{return[]}};
  const save=items=>localStorage.setItem(STORE,JSON.stringify(items));
  function settings(){
    const ema=$('emaPeriods').value.split(',').map(x=>Number(x.trim())).filter(Number.isFinite);
    const pairs=$('crossPairs').value.split(',').map(x=>x.trim()).filter(Boolean).map(x=>x.split('/').map(Number));
    if(!ema.length||ema.some(x=>!Number.isInteger(x)||x<2||x>500))throw Error('EMA: introduce períodos enteros entre 2 y 500.');
    if(pairs.some(p=>p.length!==2||!p.every(Number.isInteger)||p[0]<2||p[0]>=p[1]||p[1]>500))throw Error('Cruces EMA: usa pares como 10/20, 20/50.');
    const cfg={ema_periods:[...new Set(ema)].sort((a,b)=>a-b),cross_pairs:pairs,
      rsi_period:Number($('rsiPeriod').value),atr_period:Number($('atrPeriod').value),
      bb_period:Number($('bbPeriod').value),bb_std:Number($('bbStd').value),
      macd_fast:Number($('macdFast').value),macd_slow:Number($('macdSlow').value),macd_signal:Number($('macdSignal').value),
      volume_period:Number($('volumePeriod').value)};
    for(const k of ['rsi_period','atr_period','bb_period','macd_fast','macd_slow','macd_signal','volume_period'])if(!Number.isInteger(cfg[k])||cfg[k]<2||cfg[k]>500)throw Error(k+' debe ser entero entre 2 y 500.');
    if(cfg.macd_fast>=cfg.macd_slow)throw Error('MACD rápido debe ser menor que MACD lento.');
    if(!Number.isFinite(cfg.bb_std)||cfg.bb_std<.1||cfg.bb_std>5)throw Error('Desviación Bollinger debe estar entre 0.1 y 5.');
    return cfg;
  }
  function featureList(){
    const c=settings(),out=[['close','Precio de cierre']];
    c.ema_periods.forEach(p=>out.push(['ema_'+p,'EMA '+p]));
    out.push(['rsi_'+c.rsi_period,'RSI '+c.rsi_period],['atr_'+c.atr_period,'ATR '+c.atr_period],
      ['bb_upper_'+c.bb_period,'Bollinger superior '+c.bb_period],['bb_lower_'+c.bb_period,'Bollinger inferior '+c.bb_period],
      ['bb_upper','Bollinger superior (alias compatible)'],['bb_lower','Bollinger inferior (alias compatible)'],
      ['macd_hist_'+c.macd_fast+'_'+c.macd_slow+'_'+c.macd_signal,'MACD histograma '+c.macd_fast+'/'+c.macd_slow+'/'+c.macd_signal],
      ['macd_hist','MACD histograma (alias compatible)'],['volume_ratio_'+c.volume_period,'Volumen relativo '+c.volume_period],['volume_ratio','Volumen relativo (alias compatible)']);
    c.cross_pairs.forEach(([a,b])=>out.push(['ema_'+a+'_cross_up_ema_'+b,'Cruce alcista EMA '+a+'/'+b],['ema_'+a+'_cross_down_ema_'+b,'Cruce bajista EMA '+a+'/'+b]));
    out.push(['session_asia_open','Apertura Tokio'],['session_london_open','Apertura Londres'],['session_new_york_open','Apertura Nueva York']);
    return out;
  }
  function mount(){
    const host=document.createElement('section');host.className='panel';host.id='visualBuilder';
    host.innerHTML='<div class="head"><h2>08 / Constructor visual avanzado</h2><span class="pill">Indicadores configurables · Multi-TF</span></div>'+
      '<p class="hint">Define períodos y eventos. Cada condición puede usar la temporalidad de ejecución o una temporalidad superior. Los datos superiores solo estarán disponibles después del cierre de su vela, evitando anticipación.</p>'+
      '<div class="sectionlabel">CONFIGURACIÓN DE INDICADORES</div><div class="formgrid">'+
      '<div class="field"><label>Períodos EMA (separados por coma)</label><input id="emaPeriods" value="10,20,50,100,200"></div>'+
      '<div class="field"><label>Pares de cruce EMA</label><input id="crossPairs" value="10/20,20/50,50/200"></div>'+
      '<div class="field"><label>Período RSI</label><input id="rsiPeriod" type="number" min="2" max="500" value="14"></div>'+
      '<div class="field"><label>Período ATR</label><input id="atrPeriod" type="number" min="2" max="500" value="14"></div>'+
      '<div class="field"><label>Período Bollinger</label><input id="bbPeriod" type="number" min="2" max="500" value="20"></div>'+
      '<div class="field"><label>Desviación Bollinger</label><input id="bbStd" type="number" min=".1" max="5" step=".1" value="2"></div>'+
      '<div class="field"><label>MACD rápido</label><input id="macdFast" type="number" min="2" max="500" value="12"></div>'+
      '<div class="field"><label>MACD lento</label><input id="macdSlow" type="number" min="2" max="500" value="26"></div>'+
      '<div class="field"><label>MACD señal</label><input id="macdSignal" type="number" min="2" max="500" value="9"></div>'+
      '<div class="field"><label>Media de volumen</label><input id="volumePeriod" type="number" min="2" max="500" value="20"></div></div>'+
      '<div class="btnrow"><button class="btn secondary" id="refreshCatalog" type="button">Actualizar catálogo</button></div>'+
      '<div class="sectionlabel">ENTRADAS</div><div id="entryRules" class="grid" style="grid-template-columns:1fr 1fr;gap:10px"></div>'+
      '<div class="sectionlabel">SALIDAS POR CONDICIÓN</div><div id="exitRules" class="grid" style="grid-template-columns:1fr 1fr;gap:10px"></div>'+
      '<div class="btnrow"><button class="btn secondary" id="importNatural" type="button">Combinar reglas del texto</button><button class="btn secondary" id="resetVisual" type="button">Limpiar reglas visuales</button><button class="btn" id="saveVisual" type="button">Guardar en biblioteca</button><button class="btn secondary" id="exportVisual" type="button">Exportar JSON</button><button class="btn" id="runVisual" type="button">Ejecutar backtest</button></div>'+
      '<div class="statusline" id="visualStatus">Configura indicadores, añade reglas y guarda con un nombre.</div><div id="visualResult" class="rules" hidden></div>'+
      '<div class="sectionlabel">BIBLIOTECA DE ESTRATEGIAS</div><div id="visualLibrary" class="library"></div>';
    document.querySelector('.right').append(host);
    groups.forEach(([key,label])=>{const box=document.createElement('div');box.className='panel';box.style.padding='12px';box.innerHTML='<div class="head"><h2>'+label+'</h2><button type="button" class="btn secondary" data-add="'+key+'">+ Regla</button></div><div id="rules-'+key+'" class="grid" style="gap:7px"></div>';(key==='long'||key==='short'?$('entryRules'):$('exitRules')).append(box)});
    host.querySelectorAll('[data-add]').forEach(b=>b.addEventListener('click',()=>addRule(b.dataset.add)));
    $('refreshCatalog').addEventListener('click',()=>{try{settings();renderRules();status('Catálogo actualizado con los períodos seleccionados.')}catch(e){status(e.message,true)}});
    $('timeframe').addEventListener('change',()=>{const base=$('timeframe').value;Object.keys(state.rules).forEach(k=>state.rules[k].forEach(r=>{if(r.timeframe&&seconds[r.timeframe]<seconds[base])r.timeframe=base}));renderRules();status('Temporalidad base actualizada. Las reglas que quedaron por debajo se ajustaron a '+base+'.')});
    ['emaPeriods','crossPairs','rsiPeriod','atrPeriod','bbPeriod','bbStd','macdFast','macdSlow','macdSignal','volumePeriod'].forEach(id=>$(id).addEventListener('change',()=>{try{settings();renderRules();status('Parámetros actualizados. Las reglas con períodos retirados deben revisarse.')}catch(e){status(e.message,true)}}));
    $('importNatural').addEventListener('click',importNatural);
    $('resetVisual').addEventListener('click',()=>{Object.keys(state.rules).forEach(k=>state.rules[k]=[]);renderRules();status('Reglas visuales eliminadas.')});
    $('saveVisual').addEventListener('click',saveStrategy);$('exportVisual').addEventListener('click',exportStrategy);$('runVisual').addEventListener('click',runBacktest);
    renderRules();renderLibrary();
  }
  function timeframeOptions(selected){
    const base=$('timeframe').value;return timeframes.filter(tf=>seconds[tf]>=seconds[base]).map(tf=>'<option value="'+tf+'" '+(tf===selected?'selected':'')+'>'+tf+'</option>').join('');
  }
  function addRule(group,rule={feature:featureList()[0][0],operator:'>',value:0.5,timeframe:$('timeframe').value}){state.rules[group].push({...rule,timeframe:rule.timeframe||$('timeframe').value});renderRules()}
  function renderRules(){
    const opts=featureList();
    groups.forEach(([group])=>{const box=$('rules-'+group);box.innerHTML='';
      state.rules[group].forEach((r,i)=>{
        const row=document.createElement('div');row.style.cssText='display:grid;grid-template-columns:minmax(0,1.6fr) 58px minmax(65px,1fr) 70px 30px;gap:5px;align-items:center';
        const feature=document.createElement('select');feature.innerHTML=opts.map(([v,l])=>'<option value="'+v+'">'+l+'</option>').join('');feature.value=r.feature;
        const op=document.createElement('select');op.innerHTML=['>','<','>=','<='].map(v=>'<option>'+v+'</option>').join('');op.value=r.operator;
        const value=document.createElement('input');value.type='text';value.value=r.value;value.placeholder='valor o indicador';
        const tf=document.createElement('select');tf.innerHTML=timeframeOptions(r.timeframe||$('timeframe').value);
        const del=document.createElement('button');del.type='button';del.className='btn secondary';del.textContent='×';
        feature.addEventListener('change',()=>r.feature=feature.value);op.addEventListener('change',()=>r.operator=op.value);
        value.addEventListener('change',()=>{const n=Number(value.value);r.value=value.value.trim()!==''&&Number.isFinite(n)?n:value.value.trim()});
        tf.addEventListener('change',()=>r.timeframe=tf.value);del.addEventListener('click',()=>{state.rules[group].splice(i,1);renderRules()});
        row.append(feature,op,value,tf,del);box.append(row);
      });
      if(!state.rules[group].length){const p=document.createElement('div');p.className='empty';p.textContent='Sin condiciones';box.append(p)}
    });
  }
  function status(msg,bad=false){$('visualStatus').textContent=msg;$('visualStatus').className='statusline '+(bad?'warning':'ok')}
  function currentStrategy(){
    const read=key=>state.rules[key].map(r=>({feature:r.feature,operator:r.operator,value:(typeof r.value==='string'&&r.value.trim()!==''&&!Number.isFinite(Number(r.value)))?r.value:Number(r.value),timeframe:r.timeframe||$('timeframe').value}));
    const long=read('long'),short=read('short');if(!long.length||!short.length)throw Error('Define al menos una condición de entrada LONG y una SHORT.');
    const name=$('strategyName').value.trim();if(!name)throw Error('Escribe un nombre para la estrategia.');
    return {name,long_conditions:long,short_conditions:short,long_exit_conditions:read('longExit'),short_exit_conditions:read('shortExit'),
      indicator_settings:settings(),stop_atr:Number($('stopAtr').value),reward_risk:Number($('rewardRisk').value),
      risk_per_trade_pct:Number($('riskPct').value),max_holding_bars:Number($('maxHolding').value)};
  }
  async function importNatural(){
    try{const description=$('description').value.trim();if(!description)throw Error('Escribe primero una descripción.');
      const res=await fetch(API+'/api/interpret',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description,name:$('strategyName').value})});
      const data=await res.json();if(!res.ok||!data.ok)throw Error(data.error||'No se pudo interpretar el texto.');
      document.dispatchEvent(new Event('bgm:strategy-interpreted'));
      ['long','short'].forEach(k=>state.rules[k].push(...data.strategy[k+'_conditions'].map(x=>({...x,timeframe:$('timeframe').value}))));
      renderRules();status('Reglas del texto combinadas. Selecciona la temporalidad adecuada para cada condición.');
    }catch(e){status(e.message,true)}
  }
  function config(){return {market:'BTCUSDT',timeframe:$('timeframe').value,candles:Number($('candles').value),initial_equity:Number($('initialEquity').value),
    fee_bps:Number($('feeBps').value),slippage_bps:Number($('slippageBps').value),strategy:currentStrategy()}}
  function exportStrategy(){
    try{const p=config(),blob=new Blob([JSON.stringify(p,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
      const a=document.createElement('a');a.href=url;a.download=(p.strategy.name||'bgm-strategy').toLowerCase().replace(/[^a-z0-9]+/g,'-')+'.json';a.click();URL.revokeObjectURL(url);
      status('JSON exportado con períodos y temporalidades de cada regla.');
    }catch(e){status(e.message,true)}
  }
  function saveStrategy(){
    try{const p=config(),items=load(),id=state.active||'visual-'+Date.now(),old=items.find(x=>x.id===id);
      const savedConfig={timeframe:p.timeframe,candles:p.candles,initial_equity:p.initial_equity,fee_bps:p.fee_bps,slippage_bps:p.slippage_bps};
      const unchanged=old&&JSON.stringify(old.strategy)===JSON.stringify(p.strategy)&&JSON.stringify(old.config)===JSON.stringify(savedConfig);
      const item={id,name:p.strategy.name,saved_at:old?.saved_at||new Date().toISOString(),strategy:p.strategy,
        config:savedConfig,last_result:unchanged?old.last_result:null};
      save([item,...items.filter(x=>x.id!==id)]);state.active=id;renderLibrary();document.dispatchEvent(new Event('bgm:strategy-saved'));status('Estrategia guardada en la biblioteca local.');
    }catch(e){status(e.message,true)}
  }
  function renderLibrary(){
    const box=$('visualLibrary');if(!box)return;const items=load();box.innerHTML='';
    if(!items.length){box.innerHTML='<div class="empty">No hay estrategias guardadas todavía.</div>';return}
    items.forEach(item=>{const row=document.createElement('div');row.className='saved';const info=document.createElement('div'),name=document.createElement('b'),meta=document.createElement('small');
      name.textContent=item.name;meta.textContent=item.config.timeframe+' · '+(item.last_result?'OOS '+Number(item.last_result.net_return_pct).toFixed(2)+'%':'Sin backtest');
      if(item.last_result)name.style.color=item.last_result.net_return_pct>0?'#80a8ff':item.last_result.net_return_pct<0?'#f07886':'#aab5c5';
      info.append(name,meta);const actions=document.createElement('div');actions.className='btnrow';
      const use=document.createElement('button');use.className='btn secondary';use.textContent='Cargar';use.addEventListener('click',()=>loadStrategy(item.id));
      const del=document.createElement('button');del.className='btn secondary';del.textContent='Eliminar';del.addEventListener('click',()=>{save(load().filter(x=>x.id!==item.id));renderLibrary()});
      actions.append(use,del);row.append(info,actions);box.append(row);
    });
  }
  function loadStrategy(id){
    const item=load().find(x=>x.id===id);if(!item)return;state.active=id;const c=item.strategy.indicator_settings||{};
    $('emaPeriods').value=(c.ema_periods||[10,20,50,100,200]).join(',');$('crossPairs').value=(c.cross_pairs||[[10,20],[20,50],[50,200]]).map(p=>p.join('/')).join(',');
    $('rsiPeriod').value=c.rsi_period||14;$('atrPeriod').value=c.atr_period||14;$('bbPeriod').value=c.bb_period||20;$('bbStd').value=c.bb_std||2;
    $('macdFast').value=c.macd_fast||12;$('macdSlow').value=c.macd_slow||26;$('macdSignal').value=c.macd_signal||9;$('volumePeriod').value=c.volume_period||20;
    $('strategyName').value=item.name;$('timeframe').value=item.config.timeframe;$('candles').value=String(item.config.candles);
    $('initialEquity').value=item.config.initial_equity;$('feeBps').value=item.config.fee_bps;$('slippageBps').value=item.config.slippage_bps;
    $('stopAtr').value=item.strategy.stop_atr;$('rewardRisk').value=item.strategy.reward_risk;$('riskPct').value=item.strategy.risk_per_trade_pct;$('maxHolding').value=item.strategy.max_holding_bars;
    ['long','short','longExit','shortExit'].forEach((k,i)=>{const key=['long_conditions','short_conditions','long_exit_conditions','short_exit_conditions'][i];state.rules[k]=item.strategy[key]||[]});
    renderRules();status('Estrategia cargada. Puedes editar períodos y temporalidades.');
  }
  function showResult(r){const box=$('visualResult');box.hidden=false;const cls=r.net_return_pct>0?'positive':r.net_return_pct<0?'negative':'';
    box.innerHTML='<strong>Resultado OUT-OF-SAMPLE</strong><div class="'+cls+'">Retorno neto: '+Number(r.net_return_pct).toFixed(2)+'% · Win rate: '+Number(r.win_rate_pct).toFixed(1)+'% · Profit factor: '+(r.profit_factor==null?'N/D':Number(r.profit_factor).toFixed(2))+' · Operaciones: '+r.trades+' · Drawdown: '+Number(r.max_drawdown_pct).toFixed(2)+'%</div>'}
  async function runBacktest(){
    let p;try{p=config()}catch(e){status(e.message,true);return}const button=$('runVisual');button.disabled=true;status('Descargando velas reales de las temporalidades solicitadas…');
    try{const res=await fetch(API+'/api/backtest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});const data=await res.json();
      if(!res.ok||!data.ok)throw Error(data.error||'El motor no pudo completar el backtest.');
      showResult(data.out_of_sample);document.dispatchEvent(new CustomEvent('bgm:backtest-completed',{detail:{timeframe:p.timeframe,market:'BTCUSDT',trades:data.out_of_sample.trades,net_return_pct:data.out_of_sample.net_return_pct,status:'success'}}));const items=load(),id=state.active||'visual-'+Date.now(),old=items.find(x=>x.id===id);
      const item={id,name:p.strategy.name,saved_at:old?.saved_at||new Date().toISOString(),strategy:p.strategy,
        config:{timeframe:p.timeframe,candles:p.candles,initial_equity:p.initial_equity,fee_bps:p.fee_bps,slippage_bps:p.slippage_bps},
        last_result:{net_return_pct:data.out_of_sample.net_return_pct,win_rate_pct:data.out_of_sample.win_rate_pct,profit_factor:data.out_of_sample.profit_factor,trades:data.out_of_sample.trades,max_drawdown_pct:data.out_of_sample.max_drawdown_pct,data_start:data.data_start,data_end:data.data_end}};
      save([item,...items.filter(x=>x.id!==id)]);state.active=id;renderLibrary();
      status('Backtest completado con '+data.candles_used+' velas reales, base '+data.timeframe+'. Datos: '+data.data_start+' a '+data.data_end+'.');
    }catch(e){status(e.message,true)}finally{button.disabled=false}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();