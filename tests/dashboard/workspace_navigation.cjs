const {chromium}=require('playwright');
const fs=require('fs');
const root=require('path').resolve(__dirname,'../../src/vasa/dashboard');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 try {
 const page=await browser.newPage();const errors=[];const mutations=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://vasa.test/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 if(req.method()!=='GET')mutations.push(path);
 if(path==='/dashboard')return route.fulfill({contentType:'text/html',body:fs.readFileSync(root+'/templates/dashboard.html','utf8')});
 if(path.startsWith('/dashboard/assets/'))return route.fulfill({contentType:path.endsWith('.png')?'image/png':path.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(root+'/assets/'+path.split('/').pop())});
 const data=path==='/api/auth/me'?{email:'fixture@example.invalid',csrf_token:'fixture'}:path==='/api/whatsapp/instances'?[{id:'fixture-instance',name:'Support'}]:path.endsWith('/status')?{connected:true,logged_in:true,name:'Support'}:path.endsWith('/phone')?{phone_number:'+15551234567'}:path==='/api/agent'?{name:'Assistant',business_name:'Example',greeting:'Hello'}:path==='/api/knowledge'?[]:path.startsWith('/api/calls')?{calls:[]}:{};
 return route.fulfill({json:data});
 });
 const check=(v,msg)=>{if(!v)throw Error(msg)};
 for(const width of [320,375,393,768,1280]){
 await page.setViewportSize({width,height:900});await page.goto('http://vasa.test/dashboard');
 await page.locator('#agent-name').waitFor();await page.waitForFunction(()=>!document.getElementById('agent-name').disabled);
 await page.locator('#agent-name').fill('Unsaved name');
 check(await page.locator('[data-workspace-section]:visible').count()===1,'initial section');
 check(await page.locator('#section-back').isDisabled(),'first back');
 await page.locator('#section-next').click();await page.waitForURL('**#connections-heading');
 await page.locator('.connection-layout').waitFor({state:'visible'});
 await page.waitForFunction(()=>document.getElementById('connected-number').textContent==='+15551234567');
 check(await page.locator('.workspace-brand img').evaluate(img=>img.complete&&img.naturalWidth===661),'approved logo');
 await page.locator('#section-back').click();await page.waitForURL('**#agent-heading');
 check(await page.locator('#agent-name').inputValue()==='Unsaved name','preserve unsaved');
 await page.locator('.workspace-nav a[href="#knowledge-heading"]').click();
 await page.locator('[data-workspace-section="knowledge"]').waitFor({state:'visible'});
 await page.goBack();await page.locator('[data-workspace-section="agent"]').waitFor({state:'visible'});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow');
 for(const key of ['agent','knowledge','calls','integrations']) {
   await page.locator(`.workspace-nav a[href="#${key}-heading"]`).click();
   await page.locator(`[data-workspace-section="${key}"]`).waitFor({state:'visible'});
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'section overflow');
 }
 check(await page.locator('.integration-options article').count()===3,'integration paths');
 await page.goto('http://vasa.test/dashboard#connections-heading');
 check(await page.locator('.connection-layout').isVisible(),'deep link');
 }
 await page.goto('http://vasa.test/dashboard#not-a-section');
 await page.locator('[data-workspace-section="agent"]').waitFor({state:'visible'});
 await page.goto('http://vasa.test/dashboard#settings-heading');
 check(await page.locator('#section-next').isDisabled(),'last next');
 check(mutations.length===0,'navigation must not mutate');check(errors.length===0,'script errors');
 console.log('WORKSPACE_SECTIONS_BROWSER_OK viewports=5 preserved_drafts=true deep_links=true no_mutations=true');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
