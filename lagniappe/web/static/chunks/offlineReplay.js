const a=async(r,n=null)=>{try{if(r._destroyed)return 0;const e=n||await r.ensureOfflineQueue();if(!e||r._destroyed||!r.online)return 0;const t=await e.replay()||0;return t&&!r._destroyed&&await r.refresh(),t}catch(e){return r.reportStartupError(e,r.elt,"offline-replay"),0}};export{a as replayOfflineQueue};
/*! Third-party licenses: /third-party-licenses.txt */
