(() => {
  const API='https://bgm-quant-lab-api.onrender.com';
  const getId=(key)=>{try{let v=localStorage.getItem(key);if(!v){v=crypto.randomUUID();localStorage.setItem(key,v)}return v}catch{return ''}};
  const visitor=getId('bgmql.visitor.v1');
  let session='';try{session=sessionStorage.getItem('bgmql.session.v1')||crypto.randomUUID();sessionStorage.setItem('bgmql.session.v1',session)}catch{}
  const send=(event_type,metadata={})=>{
    if(!visitor||!session)return;
    const body={event_type,visitor_id:visitor,session_id:session,page_path:location.pathname,metadata};
    try{fetch(API+'/api/analytics/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true}).catch(()=>{})}catch{}
  };
  window.BGMQuantAnalytics={track:send};
  send('page_view');
  document.addEventListener('bgm:strategy-saved',()=>send('strategy_saved'));
  document.addEventListener('bgm:strategy-interpreted',()=>send('strategy_interpreted'));
  document.addEventListener('bgm:backtest-completed',e=>send('backtest_completed',e.detail||{}));
  document.addEventListener('bgm:client-error',()=>send('client_error'));
})();