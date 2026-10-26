/* First-party anonymous page-view tracking; no names, phone numbers or IPs sent. */
(()=>{try{
 if(navigator.doNotTrack==='1'||window.doNotTrack==='1')return;
 const path=location.pathname;
 if(path.startsWith('/admin')||path.startsWith('/api'))return;
 const params=new URLSearchParams(location.search);
 fetch('/api/analytics/visit',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,referrer:document.referrer,utm_source:params.get('utm_source')||''}),keepalive:true}).catch(()=>{});
}catch(e){}})();
