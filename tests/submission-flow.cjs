// Run: node tests/submission-flow.cjs <path-to-playwright-package>
// API responses are mocked; no requests reach the live DB or Kakao.
const {chromium}=require(process.argv[2] || 'playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 let passed=0;
 try {
 for(const viewport of [{width:1280,height:900},{width:390,height:844}]){
  const page=await browser.newPage({viewport});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  let response={status:201,body:{ok:true}}, requests=0;
  await page.route('https://shimpyo.test/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname.startsWith('/api/')){
    if(url.pathname==='/api/programs')return route.fulfill({json:[{name:'성인 상담'}]});
    if(url.pathname.includes('/closures'))return route.fulfill({json:{days:{}}});
    if(url.pathname.includes('/availability'))return route.fulfill({json:{blocked:['12:00']}});
    requests++;
    if(response.network)return route.abort('failed');
    if(response.delay)await new Promise(r=>setTimeout(r,250));
    return route.fulfill({status:response.status,contentType:'application/json',body:response.raw??JSON.stringify(response.body)});
   }
   const file=path.join(root,url.pathname==='/'?'index.html':url.pathname.slice(1));
   if(!fs.existsSync(file))return route.fulfill({status:404,body:''});
   const type={'.html':'text/html','.css':'text/css','.js':'application/javascript','.jpg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml'}[path.extname(file)]||'application/octet-stream';
   return route.fulfill({body:fs.readFileSync(file),contentType:type});
  });
  async function contact(){
   await page.goto('https://shimpyo.test/index.html#contact');
   await page.locator('#contactForm [name=name]').fill('테스트');
   await page.locator('#contactForm [name=phone]').fill('01012345678');
   await page.locator('#contactForm [name=message]').fill('테스트 문의입니다.');
   await page.locator('#contactForm [name=consent]').check();
  }
  const failures=[{status:400,body:{error:'입력 내용을 확인해 주세요.'}},{status:429,body:{error:'잠시 후 다시 시도해 주세요.'}},{status:500,body:{error:'서버 오류'}},{status:200,body:{}},{status:201,raw:'invalid json'},{status:201,body:null},{network:true}];
  for(const failure of failures){
   response=failure;await contact();await page.locator('#contactSubmit').click();
   await page.waitForFunction(()=>!document.getElementById('contactSubmit').disabled);
   assert.equal(await page.locator('dialog').count(),0);
   assert.equal(await page.locator('#contactForm [name=message]').inputValue(),'테스트 문의입니다.');
   assert.ok(await page.locator('#contactMessage').textContent()); passed++;
  }
  response={status:201,body:{ok:true},delay:true};await contact();requests=0;
  await page.locator('#contactForm').evaluate(form=>{form.requestSubmit();form.dispatchEvent(new Event('submit',{cancelable:true}))});
  await page.locator('dialog[open]').waitFor();assert.equal(requests,1);
  assert.equal(await page.locator('dialog h2').textContent(),'문의가 정상적으로 접수되었습니다');
  await page.keyboard.press('Escape');assert.equal(await page.locator('dialog[open]').count(),1);
  await page.keyboard.press('Tab');assert.equal(await page.locator('dialog button').evaluate(el=>el===document.activeElement),true);
  await page.locator('dialog button').click();assert.equal(await page.locator('#contactOverlay').isVisible(),false);
  await page.locator(viewport.width<650?'#mobileContactOpen':'#contactOpen').click();
  assert.equal(await page.locator('#contactForm [name=name]').inputValue(),'');assert.equal(await page.locator('#contactMessage').textContent(),'');passed++;
  async function reservation(){
   await page.goto('https://shimpyo.test/booking.html');
   await page.locator('.program-choice').click();await page.locator('#wizardNext').click();
   await page.locator('#calendar button:not(:disabled)').first().click();await page.locator('#wizardNext').click();
   await page.locator('#timeGrid button:not(:disabled)').first().click();
   assert.equal(await page.locator('#timeGrid button', {hasText:'12:00'}).isDisabled(),true);
   await page.locator('#wizardNext').click();
   await page.locator('#reservationForm [name=name]').fill('예약 테스트');
   await page.locator('#reservationPhone').fill('01012345678');await page.locator('#reservationForm [name=consent]').check();
  }
  for(const failure of failures){
   response=failure;await reservation();await page.locator('#reservationSubmit').click();
   await page.waitForFunction(()=>!document.getElementById('reservationSubmit').disabled);
   assert.equal(await page.locator('dialog').count(),0);assert.equal(await page.locator('#reservationForm [name=name]').inputValue(),'예약 테스트');
   assert.ok(await page.locator('#reservationFeedback').textContent());passed++;
  }
  response={status:201,body:{receipt:'ABC1234567',status:'pending'},delay:true};await reservation();requests=0;
  await page.locator('#reservationSubmit').click();await page.locator('dialog[open]').waitFor();assert.equal(requests,1);
  assert.match(await page.locator('dialog p').textContent(),/ABC1234567/);
  assert.match(await page.locator('dialog p').textContent(),/아직 확정된 예약은 아닙니다/);
  await page.locator('dialog button').click();assert.equal(await page.locator('.wizard-pane[data-pane="1"]').isVisible(),true);
  assert.equal(await page.locator('#reservationFeedback').textContent(),'');assert.equal(await page.locator('#reservationPhone').inputValue(),'');
  await page.locator('.program-choice').click();await page.locator('#wizardNext').click();assert.equal(await page.locator('#reservationFeedback').textContent(),'');
  assert.deepEqual(errors,[]);passed++;await page.close();
 }
 console.log(`PASS: ${passed} desktop/mobile scenarios (mock APIs), no browser script errors.`);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
