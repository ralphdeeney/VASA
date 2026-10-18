"use strict";
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'../../src/vasa/dashboard');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage();const errors=[];let state='active',deny=false,deleted=false,mutations=[];
 page.on('pageerror',()=>errors.push('page_error'));page.on('dialog',d=>d.accept());
 const check=(ok,message)=>{if(!ok)throw Error(message)};
 try{
 await page.route('http://vasa.test/**',async route=>{
  const r=route.request(),p=new URL(r.url()).pathname;
  if(p==='/admin')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'templates/admin.html'))});
  if(p.startsWith('/dashboard/assets/'))return route.fulfill({contentType:p.endsWith('.png')?'image/png':p.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,'assets',p.split('/').pop()))});
  if(r.method()==='POST'){
   mutations.push({path:p,body:r.postDataJSON(),csrf:r.headers()['x-csrf-token']});
   if(p.endsWith('/status')){
    if(deny)return route.fulfill({status:409,json:{detail:'last_role_required',body:'PRIVATE_BODY_MUST_NOT_DISPLAY'}});
    state=r.postDataJSON().status;return route.fulfill({json:{status:'updated'}});
   }
   if(p.endsWith('/delete')){deleted=true;return route.fulfill({json:{status:'deleted'}});}
  }
  if(p==='/api/auth/me')return route.fulfill({json:{csrf_token:'fixture'}});
  if(p.endsWith('/overview'))return route.fulfill({json:{users:3,organizations:3,connections:2,registrations:0}});
  if(p.endsWith('/account'))return route.fulfill({json:{username:'admin',email:'fixture@example.invalid',role:'super_admin'}});
  if(p.endsWith('/health'))return route.fulfill({json:{status:'ready'}});
  return route.fulfill({json:{items:deleted?[]:[{id:'fixture-org',name:'Fixture business',email:'fixture@example.invalid',status:state,memberships:[]}],total:deleted?0:1}});
 });
 for(const width of [320,375,393,768,1440]){
  await page.setViewportSize({width,height:1000});await page.goto('http://vasa.test/admin');
  await page.waitForSelector('#admin-rows tr');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow');
  check((await page.locator('.admin-metric').first().boundingBox()).height<95,'compact totals');
 }
 await page.getByRole('button',{name:'Suspend',exact:true}).click();
 await page.waitForSelector('.admin-status-suspended');
 check(await page.locator('#admin-message').evaluate(e=>e.classList.contains('admin-feedback-success')),'green confirmation');
 check(await page.getByRole('button',{name:'Reactivate',exact:true}).count()===1,'reactivate available');
 await page.getByRole('button',{name:'Reactivate',exact:true}).click();await page.waitForSelector('.admin-status-active');
 deny=true;await page.getByRole('button',{name:'Suspend',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('admin-message').textContent.includes('last active owner'));
 check(!(await page.locator('body').textContent()).includes('PRIVATE_BODY_MUST_NOT_DISPLAY'),'allowlisted refusal');
 deny=false;
 await page.locator('#admin-directory').selectOption('organizations');await page.getByRole('button',{name:'Apply filters',exact:true}).click();await page.waitForSelector('button:has-text("Delete…")');
 await page.getByRole('button',{name:'Delete…',exact:true}).click();
 await page.locator('#admin-delete-name').fill('wrong');await page.locator('#admin-delete-password').fill('fixture-private-password');
 await page.getByRole('button',{name:'Delete organization permanently',exact:true}).click();
 check(mutations.filter(m=>m.path.endsWith('/delete')).length===0,'name confirmation prevents deletion');
 await page.locator('#admin-delete-name').fill('Fixture business');
 await page.getByRole('button',{name:'Delete organization permanently',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('admin-message').textContent.includes('registrations deleted'));
 check(await page.locator('#admin-delete-password').inputValue()==='','password cleared');
 const removal=mutations.filter(m=>m.path.endsWith('/delete'));
 check(removal.length===1&&removal[0].body.confirm===true&&removal[0].csrf==='fixture','one confirmed csrf request');
 check(errors.length===0,'no script errors');
 console.log('ADMIN_ACTIONS_BROWSER_OK viewports=5 status=true refusal=true confirmed_delete=true');
 }finally{await browser.close()}
})().catch(e=>{console.error('ADMIN_ACTIONS_BROWSER_FAILED='+e.message);process.exitCode=1});
