"use strict";
const {chromium}=require('playwright');
const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../../src/vasa/dashboard');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.VASA_ACCEPTANCE_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 const check=(value,message)=>{if(!value)throw Error(message)};
 try{
 for(const state of ['disabled','enabled','unavailable','malformed']){
  const page=await browser.newPage();const errors=[];let posts=0;
  page.on('pageerror',()=>errors.push('page_error'));
  await page.route('http://vasa.test/**',route=>{
   const r=route.request(),p=new URL(r.url()).pathname;
   if(p==='/contact')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'templates/site.html'))});
   if(p.startsWith('/dashboard/assets/'))return route.fulfill({contentType:p.endsWith('.png')?'image/png':p.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,'assets',p.split('/').pop()))});
   if(p==='/api/site/capabilities')return route.fulfill({status:state==='unavailable'?503:200,json:{contact_available:state==='enabled'?true:state==='malformed'?'true':false}});
   if(p==='/api/site/contact'){posts++;return route.fulfill({status:503,json:{detail:'DO_NOT_RENDER_RAW_RESPONSE'}});}
   return route.fulfill({status:404});
  });
  for(const width of [320,375,393,768,1280]){
   await page.setViewportSize({width,height:1000});await page.goto('http://vasa.test/contact');
   await page.waitForFunction(()=>!document.getElementById('contact-status').textContent.includes('Checking'));
   check(await page.locator('#contact-form').isVisible()===(state==='enabled'),'capability gating');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow');
   check(await page.locator('#contact-status').getAttribute('class')==='small muted','neutral availability');
   if(state==='enabled'){
    const send=await page.locator('#contact-submit').boundingBox();const actions=await page.locator('.contact-actions').boundingBox();
    check(actions.y-send.y-send.height>=24,'separated actions');
    check(send.width<400,'compact submit');
   }
  }
  check(posts===0,'no unsolicited contact submission');
  if(state==='enabled'){
   await page.locator('#contact-name').fill('Fixture');await page.locator('#contact-email').fill('fixture@example.invalid');
   await page.locator('#contact-message').fill('A fixture contact request.');await page.locator('#contact-submit').click();
   await page.waitForFunction(()=>document.getElementById('contact-status').classList.contains('error'));
   check(!(await page.locator('body').textContent()).includes('DO_NOT_RENDER_RAW_RESPONSE'),'sanitized failure');
   check(posts===1,'one bounded request');
  }
  check(errors.length===0,'script errors');await page.close();
 }
 console.log('CONTACT_LAYOUT_BROWSER_OK states=4 viewports=5 safe_failure=true');
 }finally{await browser.close()}
})().catch(e=>{console.error('CONTACT_LAYOUT_BROWSER_FAILED='+e.message);process.exitCode=1});
