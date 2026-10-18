"use strict";
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'../../src/vasa/dashboard');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.VASA_ACCEPTANCE_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 const errors=[];const posts=[];let authFailure=false;
 const context=await browser.newContext();const page=await context.newPage();
 page.on('pageerror',()=>errors.push('page_error'));
 page.on('dialog',dialog=>dialog.accept());
 const check=(v,name)=>{if(!v)throw Error(name)};
 try {
 await page.route('http://vasa.test/**',route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  if(req.method()!=='GET')posts.push({path:p,body:req.postDataJSON(),csrf:req.headers()['x-csrf-token']});
  if(p==='/admin'||p==='/admin/login')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'templates',p==='/admin'?'admin.html':'admin-login.html'))});
  if(p.startsWith('/dashboard/assets/'))return route.fulfill({contentType:p.endsWith('.png')?'image/png':p.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,'assets',p.split('/').pop()))});
  let data={};
  if(p==='/api/auth/admin/login')return route.fulfill({status:authFailure?401:200,json:authFailure?{detail:'DO_NOT_RENDER_RESPONSE'}:{csrf_token:'fixture'}});
  if(p==='/api/auth/me')data={csrf_token:'fixture'};
  else if(p.endsWith('/overview'))data={users:12,organizations:5,connections:3,registrations:2};
  else if(p.endsWith('/account'))data={username:'admin',email:'fixture@example.invalid',role:'super_admin'};
  else if(p.endsWith('/health'))data={status:'ready'};
  else if(p.endsWith('/password'))data={status:'password_changed'};
  else data={items:[{id:'fixture-id',email:'fixture@example.invalid',name:'Fixture',status:'active',memberships:[]}],total:1};
  return route.fulfill({json:data});
 });
 for(const width of [320,375,393,768,1440]){
  await page.setViewportSize({width,height:1000});
  await page.goto('http://vasa.test/admin');
  await page.waitForFunction(()=>document.querySelectorAll('#admin-rows tr').length===1);
  check(await page.locator('.admin-metric').count()===4,'real metric count');
  check(await page.locator('.admin-metric strong').first().textContent()==='12','api metric');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'admin overflow');
  check(await page.locator('.admin-brand img').evaluate(i=>i.complete&&i.naturalWidth===661),'approved logo');
  if(process.env.VASA_ADMIN_PREVIEW&&width===1440) await page.screenshot({path:process.env.VASA_ADMIN_PREVIEW,fullPage:true});
  await page.goto('http://vasa.test/admin/login');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'login overflow');
 }
 authFailure=true;
 await page.locator('#admin-username').fill('admin');
 await page.locator('#admin-login-password').fill('fixture-login-password');
 await page.locator('#admin-login-submit').click();
 await page.waitForFunction(()=>document.getElementById('admin-login-message').textContent.includes('incorrect'));
 check(!(await page.locator('body').textContent()).includes('DO_NOT_RENDER_RESPONSE'),'redacted provider body');
 authFailure=false;
 await page.locator('#admin-login-submit').click();
 await page.waitForURL('**/admin');
 await page.waitForFunction(()=>document.querySelectorAll('#admin-rows tr').length===1);
 await page.locator('#admin-current-password').fill('fixture-login-password');
 await page.locator('#admin-new-password').fill('fixture-new-password');
 await page.locator('#admin-confirm-password').fill('fixture-new-password');
 await page.locator('#admin-password-form button').click();
 await page.waitForURL('**/admin/login');
 const rotation=posts.filter(p=>p.path.endsWith('/password'));
 check(rotation.length===1&&rotation[0].csrf==='fixture','single csrf rotation');
 check(posts.filter(p=>p.path!=='/api/auth/admin/login'&&!p.path.endsWith('/password')).length===0,'no customer mutations');
 check(errors.length===0,'page errors');
 console.log('PLATFORM_ADMIN_BROWSER_OK viewports=5 login=true password_change=true no_customer_mutations=true');
 }finally{await browser.close()}
})().catch(e=>{console.error('PLATFORM_ADMIN_BROWSER_FAILED='+e.message);process.exitCode=1});
