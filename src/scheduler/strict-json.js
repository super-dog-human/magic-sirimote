'use strict';
// Validate JSON structure and reject duplicate keys before JSON.parse.
// This is an offline input-validation component, not a registered service.
function parseStrict(text,{maxBytes=4096}={}){
 if(!Number.isSafeInteger(maxBytes)||maxBytes<1||maxBytes>32768||typeof text!=='string'||Buffer.byteLength(text,'utf8')>maxBytes)throw Error('invalid input');
 let i=0,nodes=0;const ws=()=>{while(i<text.length&&' \t\r\n'.includes(text[i]))i++;};
 function str(){
  if(text[i++]!=='"')throw Error('string expected');const start=i-1;
  while(i<text.length){
   const c=text[i++];if(c==='"')return JSON.parse(text.slice(start,i));
   if(c==='\\'){if(i>=text.length)throw Error('escape');const e=text[i++];if(e==='u'){if(!/^[0-9a-fA-F]{4}$/.test(text.slice(i,i+4)))throw Error('unicode escape');i+=4;}else if(!'"\\/bfnrt'.includes(e))throw Error('escape');}
   else if(c.charCodeAt(0)<32)throw Error('control');
  }throw Error('unterminated string');
 }
 function value(depth){
  if(depth>32||++nodes>1024)throw Error('structure limit');ws();const c=text[i];
  if(c==='"'){str();return;}
  if(c==='{'){
   i++;ws();const keys=new Set();if(text[i]==='}'){i++;return;}
   for(;;){ws();const k=str();if(keys.has(k))throw Error('duplicate key');keys.add(k);ws();if(text[i++]!==':')throw Error('colon');value(depth+1);ws();if(text[i]==='}'){i++;return;}if(text[i++]!==',')throw Error('comma');}
  }
  if(c==='['){i++;ws();if(text[i]===']'){i++;return;}for(;;){value(depth+1);ws();if(text[i]===']'){i++;return;}if(text[i++]!==',')throw Error('comma');}}
  const rest=text.slice(i);const m=/^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)/.exec(rest);
  if(!m)throw Error('value');if(!['true','false','null'].includes(m[0])&&!Number.isFinite(Number(m[0])))throw Error('non-finite number');i+=m[0].length;
 }
 value(0);ws();if(i!==text.length)throw Error('trailing data');return JSON.parse(text);
}
module.exports={parseStrict};
