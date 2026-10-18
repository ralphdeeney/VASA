"use strict";
// Private runner input/result files; never pass credentials in CLI arguments.
const fs = require("node:fs");
const { chromium } = require("playwright");
const origin = "https://vasa.litatech.xyz";
async function main() {
  let browser;
  const sessions = new Set();
  let stage = "configuration";
  try {
    const file = process.env.VASA_LIVE_ACCEPTANCE_INPUT;
    const result = process.env.VASA_LIVE_ACCEPTANCE_RESULT;
    if (!file || !result || (fs.statSync(file).mode & 0o077)) throw Error();
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!/^[a-f0-9]{32}$/.test(data.run) || typeof data.password !== "string" || data.password.length < 32) throw Error();
    browser = await chromium.launch({headless:true, ...(process.env.VASA_ACCEPTANCE_CHROMIUM ? {executablePath:process.env.VASA_ACCEPTANCE_CHROMIUM} : {})});
    const pages=[];
    const check = condition => { if (!condition) throw Error(); };
    async function api(page,path,method="GET",body) {
      return page.evaluate(async ({path,method,body}) => {
        const me=await fetch("/api/auth/me");
        const csrf=me.ok ? (await me.json()).csrf_token : "";
        const response=await fetch(path,{method,headers:{"content-type":"application/json","x-csrf-token":csrf},body:body?JSON.stringify(body):undefined});
        let data=null; try {data=await response.json();} catch {}
        return {status:response.status,data};
      },{path,method,body});
    }
    for(let i=0;i<2;i++) {
      stage="login_"+i;
      const context=await browser.newContext();
      const page=await context.newPage(); pages.push(page);
      await page.goto(origin+"/login");
      await page.locator("#email").fill(`acceptance-${data.run}-${i}@example.invalid`);
      await page.locator("#password").fill(data.password);
      await page.locator("#login-submit").click();
      await page.waitForURL(origin+"/dashboard");
      for(const cookie of await context.cookies(origin)) if(cookie.name==="vasa_session")sessions.add(cookie.value);
      await page.reload(); check((await api(page,"/api/auth/me")).status===200);
    }
    console.log("LIVE_SAAS_PASS=login_session_persistence");
    stage="tenant_boundaries";
    const [admin,owner]=pages;
    const a=(await api(admin,"/api/saas/workspaces")).data.items;
    const b=(await api(owner,"/api/saas/workspaces")).data.items;
    check(a.length===1 && b.length===1 && a[0].id!==b[0].id);
    check((await api(owner,"/api/saas/workspace","POST",{tenant_id:a[0].id})).status===403);
    check((await api(owner,"/api/saas/admin/users")).status===403);
    console.log("LIVE_SAAS_PASS=workspace_tenant_platform_boundaries");
    stage="admin";
    await admin.goto(origin+"/admin");
    await admin.locator("#admin-query").fill("acceptance-"+data.run);
    await admin.locator("#admin-search button[type=submit]").click();
    await admin.waitForFunction(()=>document.querySelectorAll("#admin-rows tr").length===2);
    const audit=await api(admin,"/api/saas/admin/audit?action=identity.server_provision");
    check(audit.status===200);
    console.log("LIVE_SAAS_PASS=admin_directory_audit");
    stage="responsive";
    for(const page of pages) for(const width of [390,1440]) {
      await page.setViewportSize({width,height:900});
      check(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1));
    }
    const publicContext=await browser.newContext();
    const publicPage=await publicContext.newPage();
    let scriptError=false; publicPage.on("pageerror",()=>{scriptError=true;});
    for(const width of [390,1440]) for(const path of ["/","/features","/pricing","/login","/signup","/forgot-password","/admin/login"]) {
      await publicPage.setViewportSize({width,height:900});
      check((await publicPage.goto(origin+path)).status()===200);
      check(await publicPage.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1));
    }
    check(!scriptError); await publicContext.close();
    console.log("LIVE_SAAS_PASS=mobile_desktop");
    stage="admin_security";
    await admin.goto(origin+"/admin#security");
    await admin.waitForFunction(()=>!document.querySelector("#admin-password-form button").disabled);
    const rotated=data.password+"-rotated";
    await admin.locator("#admin-current-password").fill(data.password);
    await admin.locator("#admin-new-password").fill(rotated);
    await admin.locator("#admin-confirm-password").fill(rotated);
    admin.once("dialog",dialog=>dialog.accept());
    await admin.locator("#admin-password-form button").click();
    await admin.waitForURL(origin+"/admin/login");
    check((await api(admin,"/api/auth/me")).status===401);
    await admin.goto(origin+"/login");
    await admin.locator("#email").fill(`acceptance-${data.run}-0@example.invalid`);
    await admin.locator("#password").fill(rotated);
    await admin.locator("#login-submit").click();
    await admin.waitForURL(origin+"/dashboard");
    for(const cookie of await admin.context().cookies(origin)) if(cookie.name==="vasa_session")sessions.add(cookie.value);
    check((await api(admin,"/api/saas/admin/account")).status===200);
    console.log("LIVE_SAAS_PASS=admin_password_rotation");
    stage="logout";
    for(const page of pages) {
      await page.goto(origin+"/logout");
      await page.waitForFunction(()=>!document.getElementById("identity-submit").disabled);
      const response=page.waitForResponse(r=>r.url().endsWith("/api/auth/logout") && r.request().method()==="POST");
      await page.locator("#identity-submit").click(); check((await response).ok());
      check((await api(page,"/api/auth/me")).status===401);
    }
    console.log("LIVE_SAAS_PASS=logout_revocation");
    console.log("LIVE_SAAS_EMAIL_FLOWS=blocked_smtp");
    console.log("LIVE_SAAS_ACCEPTANCE_PARTIAL_OK");
  } catch {
    console.log("LIVE_SAAS_FAILED="+stage);
    process.exitCode=1;
  } finally {
    if(browser)await browser.close();
    if(process.env.VASA_LIVE_ACCEPTANCE_RESULT) {
      try {fs.writeFileSync(process.env.VASA_LIVE_ACCEPTANCE_RESULT,JSON.stringify({sessions:[...sessions]}),{mode:0o600,flag:"wx"});}
      catch {console.log("LIVE_SAAS_FAILED=private_result");process.exitCode=1;}
    }
  }
}
main().catch(()=>{console.log("LIVE_SAAS_FAILED=internal");process.exitCode=1;});
