"use strict";

// Destructive disposable-account acceptance; never point this at production.
const { chromium } = require("playwright");
const { randomBytes } = require("node:crypto");
const origin = process.env.VASA_ACCEPTANCE_ORIGIN;
const fixture = process.env.VASA_ACCEPTANCE_FIXTURE_ORIGIN;
const fixtureKey = process.env.VASA_ACCEPTANCE_FIXTURE_KEY;
const run = process.env.VASA_ACCEPTANCE_RUN;
function requireCheck(value) {
  if (!value) throw new Error("acceptance_failed");
}
function loopback(value) {
  const url = new URL(value);
  return url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname) && !url.username && !url.password && !url.search && !url.hash && url.pathname === "/";
}
async function main() {
  requireCheck(origin && fixture && fixtureKey && /^[a-z0-9-]{8,60}$/.test(run || ""));
  requireCheck(loopback(origin) && loopback(fixture));
  const browser = await chromium.launch({ executablePath: process.env.VASA_ACCEPTANCE_CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
  const contexts = [];
  let stage = "setup";
  const check = (name) => console.log(`SAAS_BROWSER_PASS=${name}`);
  async function fixtureCall(path, body) {
    const response = await fetch(fixture + path, { method: body ? "POST" : "GET", headers: { "x-acceptance-key": fixtureKey, "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    requireCheck(response.ok);
    return response.json();
  }
  async function api(page, path, method = "GET", body) {
    return page.evaluate(async ({path, method, body}) => {
      const me = await fetch("/api/auth/me");
      const csrf = me.ok ? (await me.json()).csrf_token : "";
      const response = await fetch(path, {method, headers: {"content-type":"application/json", "x-csrf-token":csrf}, body: body ? JSON.stringify(body) : undefined});
      let data = null;
      try { data = await response.json(); } catch {}
      return {status:response.status, data};
    }, {path,method,body});
  }
  async function identity(page, path, fields = {}) {
    await page.goto(origin + path);
    for (const [id,value] of Object.entries(fields)) await page.locator("#"+id).fill(value);
    await page.locator("#identity-submit").waitFor({state:"visible"});
    await page.waitForFunction(() => !document.getElementById("identity-submit").disabled);
    const response = page.waitForResponse(r => r.request().method() === "POST" && (r.url().includes("/api/saas/") || r.url().endsWith("/api/auth/logout")));
    await page.locator("#identity-submit").click();
    requireCheck((await response).ok());
  }
  async function login(page,email,password) {
    await page.goto(origin+"/login");
    await page.locator("#email").fill(email);
    await page.locator("#password").fill(password);
    await page.locator("#login-submit").click();
    await page.waitForURL(origin+"/dashboard");
    requireCheck((await api(page,"/api/auth/me")).status===200);
  }
  async function emailLink(email,page) {
    const data=await fixtureCall("/_acceptance/mailbox?"+new URLSearchParams({email,page}));
    const link=new URL(data.link);
    requireCheck(link.origin===new URL(origin).origin && link.pathname==="/"+page);
    return link.pathname+link.hash;
  }
  async function layout(page,width) {
    await page.setViewportSize({width,height:900});
    requireCheck(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  }
  try {
    const password="Disposable-"+randomBytes(18).toString("hex");
    const resetPassword="Replacement-"+randomBytes(18).toString("hex");
    const emails=[run+"-owner@example.invalid",run+"-member@example.invalid"];
    const pages=[];
    for(let i=0;i<2;i++) {
      stage="signup_verify_"+i;
      const context=await browser.newContext(); contexts.push(context);
      const page=await context.newPage(); pages.push(page);
      await identity(page,"/signup",{name:"Disposable acceptance",business:"Disposable workspace "+i,email:emails[i],password});
      const blocked=await api(page,"/api/auth/login","POST",{email:emails[i],password});
      requireCheck(blocked.status===403);
      await identity(page,await emailLink(emails[i],"verify-email"));
      requireCheck(await page.evaluate(() => location.hash===""));
      await login(page,emails[i],password);
      await page.reload();
      requireCheck((await api(page,"/api/auth/me")).status===200);
    }
    check("signup_email_verification_login_session_persistence");
    const [owner,member]=pages;
    stage="workspace_isolation";
    const a=(await api(owner,"/api/saas/workspaces")).data.items[0];
    const b=(await api(member,"/api/saas/workspaces")).data.items[0];
    requireCheck(a.id!==b.id);
    requireCheck((await api(member,"/api/saas/workspace","POST",{tenant_id:a.id})).status===403);
    requireCheck((await api(owner,"/api/saas/admin/users")).status===403);
    check("workspace_creation_cross_tenant_and_platform_isolation");
    stage="invitation";
    await owner.locator("#invite-email").fill(emails[1]);
    await owner.locator("#invite-role").selectOption("member");
    const invited=owner.waitForResponse(r=>r.url().endsWith("/api/saas/invitations") && r.request().method()==="POST");
    await owner.locator("#invitation-form button").click();
    requireCheck((await invited).status()===201);
    await identity(member,await emailLink(emails[1],"accept-invitation"));
    requireCheck((await api(member,"/api/saas/workspaces")).data.items.length===2);
    requireCheck((await api(member,"/api/saas/workspace","POST",{tenant_id:a.id})).status===200);
    requireCheck((await api(member,"/api/saas/team")).status===403);
    requireCheck((await api(member,"/api/saas/invitations","POST",{email:run+"-other@example.invalid",role:"admin"})).status===403);
    requireCheck((await api(member,"/api/saas/workspace","POST",{tenant_id:b.id})).status===200);
    check("invitation_acceptance_membership_switch_and_role_permissions");
    stage="password_recovery";
    const stale=await browser.newContext({storageState:await contexts[1].storageState()}); contexts.push(stale);
    const stalePage=await stale.newPage(); await stalePage.goto(origin+"/dashboard");
    await identity(member,"/forgot-password",{email:emails[1]});
    await identity(member,await emailLink(emails[1],"reset-password"),{password:resetPassword});
    requireCheck((await api(stalePage,"/api/auth/me")).status===401);
    await login(member,emails[1],resetPassword);
    await identity(member,"/logout");
    requireCheck((await api(member,"/api/auth/me")).status===401);
    check("password_recovery_revokes_existing_sessions_logout");
    stage="admin";
    await fixtureCall("/_acceptance/admin",{email:emails[0]});
    await owner.goto(origin+"/admin");
    await owner.locator("#admin-query").fill(run);
    await owner.locator("#admin-search button[type=submit]").click();
    await owner.waitForFunction(() => document.querySelectorAll("#admin-rows tr").length===2);
    const audit=await api(owner,"/api/saas/admin/audit");
    requireCheck(audit.status===200 && audit.data.items.some(item=>item.action==="identity.password_reset"));
    check("admin_registered_user_directory_and_audit_visibility");
    stage="responsive";
    for(const path of ["/", "/signup", "/login", "/dashboard", "/admin"]) {
      await owner.goto(origin+path);
      await layout(owner,390); await layout(owner,1440);
    }
    check("mobile_desktop_no_horizontal_overflow");
    console.log("SAAS_BROWSER_ACCEPTANCE_OK");
  } catch {
    console.log(`SAAS_BROWSER_FAILED=${stage}`);
    process.exitCode=1;
  } finally {
    for(const context of contexts) await context.close();
    await browser.close();
  }
}
main().catch(() => { console.log("SAAS_BROWSER_FAILED=configuration"); process.exitCode=1; });
