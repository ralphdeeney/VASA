"use strict";
const {chromium}=require('playwright');
const fs=require('fs');const path=require('path');
const root=path.resolve(__dirname,'../../src/vasa/dashboard');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.VASA_ACCEPTANCE_CHROMIUM||'/usr/bin/chromium',args:['--no-sandbox']});
 const check=(v,m)=>{if(!v)throw Error(m)};
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',()=>errors.push('page_error'));
 const identity=['/signup','/verify-email','/resend-verification','/forgot-password','/reset-password','/accept-invitation','/logout'];
 const publicPages=['/','/features','/how-it-works','/pricing','/contact','/login','/403','/404',...identity];
 await page.route('http://vasa.test/**',route=>{
  const p=new URL(route.request().url()).pathname;
  if(p.startsWith('/dashboard/assets/'))return route.fulfill({contentType:p.endsWith('.png')?'image/png':p.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,'assets',p.split('/').pop()))});
  if(p==='/api/site/capabilities')return route.fulfill({json:{contact_available:false,signup_available:true,email_delivery_available:true,saas_enabled:true}});
  const name=p==='/login'?'login.html':identity.includes(p)?'identity.html':['/403','/404'].includes(p)?'error.html':'site.html';
  return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'templates',name))});
 });
 for(const width of [320,393,768,1280])for(const p of publicPages){
  await page.setViewportSize({width,height:900});await page.goto('http://vasa.test'+p);
  await page.locator('.site-brand img').first().waitFor();
  const valid=await page.locator('.site-brand img').evaluateAll(images=>images.length>0&&images.every(i=>i.complete&&i.naturalWidth===661&&i.naturalHeight===548&&i.alt==='VASA'&&new URL(i.src).pathname==='/dashboard/assets/vasa-logo.png'&&Math.abs(i.width/i.height-661/548)<.02));
  check(valid,'approved image '+p);
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow '+p);
 }
 check(errors.length===0,'script errors');
 console.log('PUBLIC_BRANDING_BROWSER_OK routes='+publicPages.length+' viewports=4 approved_image=true');
 }finally{await browser.close()}
})().catch(e=>{console.error('PUBLIC_BRANDING_BROWSER_FAILED='+e.message);process.exitCode=1});
