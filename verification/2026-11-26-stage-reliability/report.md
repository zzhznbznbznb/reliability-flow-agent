# 鍙潬鎬ф祦绋嬩豢鐪熸敼閫犱笌瀹炴祴鎶ュ憡

鏃ユ湡锛?026-11-26  
椤圭洰鐩綍锛歚C:\Users\woain\Desktop\reliability-flow-agent`

## 0. 缁撹鎽樿

鏈鏀归€犲凡缁忓畬鎴愬苟閫氳繃鐪熷疄杩愯楠岃瘉锛?
- 椤甸潰涓儴涓婇儴鏀逛负鍏」椤圭洰鍙傛暟鍖哄煙锛屽叚椤瑰叏閮ㄥ悎娉曞悗鎵嶅厑璁歌繍琛屼豢鐪熴€?- 椤圭洰鍙傛暟鐪熷疄浼犲叆鍚庣锛屽苟鍐欏叆 `SimulationResult.project`銆佸疄楠岃褰曞拰瀹為獙鍒楄〃銆?- 鍙湁闃舵 subprocess 閰嶇疆鏁呴殰鐜?位锛涙櫘閫?task 鍙湁鎸佺画鏃堕棿锛涙祴璇曡妭鐐瑰崟鐙厤缃?Ft銆?- 璐瓨 位1銆佸€肩彮 位2 鎸夊浘鐗?1 鐨勯€愭椂闂存 `p(t)` 涓?`R(t)=exp(-位t)` 姣旇緝鎵ц銆?- 娴嬭瘯鑺傜偣鎸夊浘鐗?2 姣忔娴嬭瘯鍙娊鍙栦竴娆?`pt`锛屾寜 `Ft` 鍒ゆ柇鏄惁鍙戠幇鏁呴殰銆?- 6 缁勬晠闅滅巼銆? 缁勬娴嬬巼銆佸浐瀹氱瀛愩€佺悊璁哄鐓у潎宸插疄娴嬪苟淇濆瓨缁撴灉銆?- 鐪熷疄 Web 椤甸潰閫氳繃 Microsoft Edge + Playwright 椹卞姩锛?3 椤规柇瑷€鍏ㄩ儴閫氳繃锛屾埅鍥句繚瀛樺湪鏈洰褰曘€?- 鍚庣娴嬭瘯锛?*288 passed**锛涘墠绔€昏緫娴嬭瘯锛?*35 passed**銆?
## 1. 鍙傝€冨浘鐗囦笌浠ｇ爜瀵瑰簲

瀹為檯鍥剧墖鏂囦欢锛?
- 鍥剧墖 1锛堝崟闃舵鍙潬搴︽娊鍙栵級锛歚docs/reference/d8c8228abf78592c9959d8571f2a0212.png`
- 鍥剧墖 2锛堟晠闅滄娴嬬巼澶勭悊锛夛細`docs/reference/4cb48c525b13da957dfac5fa09626f7e.png`
- 涓氬姟娴佺▼鍥撅細`docs/reference/equipment_support_nested_reference.jpg`

瀵瑰簲瀹炵幇锛?
- 鍥剧墖 1锛歚app/simulation/engine.py` 鐨?`_sample_stage_task()`銆?- 鍥剧墖 2锛歚app/simulation/engine.py` 鐨?`_run_detection()`銆乣_register_failure()`銆乣_maybe_mark_repair_start()`銆?- 闃舵/娴嬭瘯鍙傛暟缁撴瀯锛歚app/domain/reliability_ir.py` 鐨?`ReliabilityNodeConfig`銆?- 鍙傛暟鏍￠獙锛歚app/domain/reliability_validation.py` 鐨?`validate_reliability()`銆?- 娴嬭瘯鐢ㄤ緥锛歚tests/test_stage_reliability_runtime.py`銆乣tests/test_multi_group_reliability.py`銆乣tests/test_project_simulation_api.py`銆?
## 2. 淇敼鏂囦欢涓庝富瑕佸嚱鏁?
### 鍚庣

| 鏂囦欢 | 淇敼/鏂板 |
|---|---|
| `app/domain/reliability_ir.py` | 鏂板 `module_type`锛坅ctivity/stage/test锛夈€乣detection_rate`銆乣test_time`銆乣stage_task_id`锛浳?鍗曚綅鎵╁睍涓?per_hour/per_day/per_month/per_year |
| `app/domain/reliability_validation.py` | 鎸夋ā鍧楃被鍨嬫牎楠岋細闃舵蹇呴』鎸?subprocess 涓旀湁 位锛涙祴璇曞繀椤绘槸 task 涓旀湁 Ft銆佷笉鑳芥湁 位锛涙櫘閫氭椿鍔ㄤ笉瑕佹眰 位 |
| `app/simulation/config.py` | 鏂板 `ProjectParameters`銆乣simulation_unit`銆乣reliability_step`锛沗project.missile_count` 涓?`entity_count` 涓€鑷存€ф牎楠?|
| `app/simulation/models.py` | 鏂板 `FailureRecord`銆乣TestRecord`锛沗ReliabilitySample` 澧炲姞 module_type/stage_task_id/sampling_mode/cumulative_exposure/step_index锛涘疄浣撶粨鏋滃鍔犲彲鐢?涓嶅彲鐢ㄦ椂闂村拰鏁呴殰/娴嬭瘯璁板綍锛涗豢鐪熺粨鏋滃鍔?project/simulation_unit |
| `app/simulation/engine.py` | 鏂板 `_index_reliability_modules`銆乣_sample_stage_task`銆乣_run_detection`銆乣_register_failure`銆乣_maybe_mark_repair_start`銆乣_finalize_availability`锛涗慨鏀?`_validate`銆乣_enter_node`銆乣_complete_node`銆乣_finish_at_simulation_end`銆乣_build_result`銆乣_field_value` |
| `app/simulation/rng.py` | 鏂板 `DETECTION_STREAM`锛屾娴嬮殢鏈烘暟涓庢晠闅滄娊鏍烽殢鏈烘暟闅旂 |
| `app/evaluation/models.py` | 鏂板 `TestMetrics`銆乣readiness`銆佸彲鐢?涓嶅彲鐢ㄦ椂闂淬€侀樁娈垫ā鍧楀瓧娈点€乣readiness_min` 鐩爣 |
| `app/evaluation/evaluator.py` | 鏀寔闃舵/娴嬭瘯妯″潡璇勪环銆佹垬澶囧畬濂藉害銆佸彲鐢?涓嶅彲鐢ㄦ椂闂淬€佹娴嬫寚鏍囥€乺eadiness 鐩爣 |
| `app/evaluation/explanations.py` | 澧炲姞鎴樺瀹屽ソ搴﹀拰鍙敤/涓嶅彲鐢ㄦ椂闂磋В閲?|
| `app/agent/domain_rules.py` | 鎺ュ彈杩愯鏃跺啓鍏ョ殑 `test_detected`/`last_test_detected` 浣滀负鏁呴殰鍒ゆ柇鏁版嵁鏉ユ簮 |
| `app/domain/validation.py` | 鏂板 `test_detected` 绛夊唴缃潯浠跺瓧娈碉紱鍏佽甯︽妧鏈惊鐜嚭鍙ｇ殑鎸佺画娴佺▼ |
| `app/experiments/store.py` | 瀹為獙璁板綍鎸佷箙鍖?`project`锛屽疄楠屽垪琛ㄨ繑鍥?`project_name` |
| `app/api/experiment_routes.py` | 姝ｅ紡瀹為獙鎺ュ彛寮哄埗瑕佹眰瀹屾暣椤圭洰鍙傛暟锛岀己澶辨椂杩斿洖 `missing_project_parameters` |

### 鍓嶇

| 鏂囦欢 | 淇敼/鏂板 |
|---|---|
| `frontend/src/project.js` | 鍏」椤圭洰鍙傛暟瀹氫箟銆佹牎楠屻€佸崟浣嶆槧灏勩€佺洰鏍囧拰 payload 鏋勯€?|
| `frontend/src/components/ProjectPanel.jsx` | 鏂扮殑椤圭洰鍙傛暟鍖哄煙 |
| `frontend/src/App.jsx` | 椤圭洰鍙傛暟鐘舵€?鏈湴鎸佷箙鍖栥€佸叚椤规牎楠屻€佽繍琛屽墠鍙傛暟妫€鏌ャ€佄?鍙傛暟鎸夐挳銆佸睍寮€瀛愭祦绋嬭嚜鍔ㄨ仛鐒︺€佺敾甯?fit/缂╂斁 |
| `frontend/src/components/Inspector.jsx` | subprocess 闃舵 位 + 闃舵涓讳换鍔★紱task 娴嬭瘯妯″潡 Ft/娴嬭瘯鏃堕棿锛涙櫘閫氭椿鍔ㄤ笉鍐嶆樉绀?位 杈撳叆 |
| `frontend/src/components/SimulationPanel.jsx` | 鐩爣鍊?瀵煎脊鏁伴噺鏉ヨ嚜椤圭洰鍙傛暟锛況eadiness銆佸彲鐢?涓嶅彲鐢ㄦ椂闂淬€侀樁娈?娴嬭瘯鎸囨爣灞曠ず锛涜繍琛屽墠妫€鏌?|
| `frontend/src/reliability.js` | 鏂扮殑鍙潬鎬ц妭鐐规瀯閫犮€丗t/娴嬭瘯鏃堕棿鏍￠獙銆佽繍琛屽墠鍙潬鎬у弬鏁版鏌?|
| `frontend/src/flow/nested.js` | 鍙潬鎬ц妭鐐瑰垪琛ㄣ€侀樁娈?位 鏍囩銆佹祴璇曟ā鍧楁爣绛俱€佺敾甯冮棿璺濄€佸瓙娴佺▼鑱氱劍鑺傜偣闆嗗悎 |
| `frontend/src/flow/nodes.jsx` | subprocess 鍙充晶 位 鍙傛暟鎸夐挳銆侀樁娈?位 鏍囩銆佹祴璇曟ā鍧楁爣璁?|
| `frontend/src/simulation.js` | readiness 鎸囨爣鏍囩銆侀」鐩洰鏍囪浆鎹?|
| `frontend/src/styles.css` | 椤圭洰鍙傛暟鍖哄煙銆侀樁娈靛弬鏁版寜閽€乺eadiness 鎻愮ず绛夋牱寮?|
| `frontend/tests/project.test.mjs` | 椤圭洰鍙傛暟娴嬭瘯 |
| `frontend/tests/reliability.test.mjs` | 杩愯鍓嶅彲闈犳€у弬鏁版鏌ユ祴璇?|

### 鏂扮ず渚嬩笌楠岃瘉璧勪骇

- `examples/equipment_support_reliability_flow.json`锛氶樁娈?位銆佹祴璇?Ft銆佹寔缁€肩彮鐨勮鑼冩祦绋嬨€?- `tests/test_stage_reliability_runtime.py`锛氶樁娈垫娊鏍枫€佹娴嬨€佺淮淇洖璺€佹椂闂磋褰曘€乽navailable 缁熻銆佸崟浣嶆牎楠屻€侀」鐩拷婧€?- `tests/test_multi_group_reliability.py`锛欰-F 鍏粍鏁呴殰鐜囪秼鍔垮拰 Ft 瀵圭収銆?- `tests/test_project_simulation_api.py`锛氶」鐩弬鏁板己鍒躲€佸疄楠屾寔涔呭寲銆侀樁娈?娴嬭瘯鎸囨爣銆?- `verification/2026-11-26-stage-reliability/web_e2e.py`锛氱湡瀹炴祻瑙堝櫒 E2E銆?- `verification/2026-11-26-stage-reliability/run_matrix.py`锛氬叚缁勬晠闅滅巼/妫€娴嬬巼瀹炴祴銆?- `verification/2026-11-26-stage-reliability/matrix_report.md`銆乣matrix_results.json`銆?- `verification/2026-11-26-stage-reliability/web_e2e_summary.json` 鍙婃埅鍥俱€?
## 3. 椤甸潰璋冩暣缁撴灉

- 椤甸潰涓棿涓婇儴鐜板湪鏄剧ず鈥淧ROJECT PARAMETERS / 椤圭洰鍩烘湰淇℃伅涓庝豢鐪熺洰鏍団€濆尯鍩熴€?- 鍏」杈撳叆锛氶」鐩悕绉般€侀」鐩弿杩般€佽澶囦娇鐢ㄥ彲闈犲害鐩爣鍊笺€佹垬澶囧畬濂藉害鐩爣鍊笺€佷豢鐪熷崟浣嶃€佸寮规€绘暟閲忋€?- 姣忎竴瀛楁鍧囨湁蹇呭～銆佺被鍨嬪拰鑼冨洿鏍￠獙锛涢敊璇洿鎺ユ樉绀哄湪瀛楁涓嬫柟銆?- 鍏」鏈叏閮ㄥ悎娉曟椂锛?  - 椤圭洰鍖虹殑鈥滄墦寮€浠跨湡杩愯鈥濇寜閽鐢紱
  - 鍗充娇浠跨湡闈㈡澘宸叉墦寮€锛屸€滆繍琛屼豢鐪熷苟璇勪环鈥濇寜閽篃淇濇寔绂佺敤锛?  - 椤甸潰鏄剧ず缂哄皯鍝簺鍙傛暟銆?- 鍘熸祦绋嬪悕绉般€佹湭淇濆瓨鐘舵€併€佺増鏈€佸搱甯屻€佹牎楠岀姸鎬佷繚鐣欏湪椤圭洰鍖轰笅鏂圭殑娴佺▼宸ュ叿鏉′腑锛屼笉鍐嶅崰鎹富瑕佸尯鍩熴€?- 鍘熸潵鐨勨€? 浠诲姟銆? 鍒ゆ柇銆? 寮€濮嬨€? 缁撴潫銆? 宓屽鍧椻€濈瓑妯″瀷缂栬緫鍏ュ彛淇濈暀鍦ㄦ祦绋嬪伐鍏锋潯涓€?- 杩愯鍓嶆鏌ヨ繕鍖呮嫭锛氭祦绋嬪凡淇濆瓨銆佹棤鏈繚瀛樹慨鏀广€佺粨鏋勬牎楠岄€氳繃銆丷eliability 宸茬粦瀹氥€侀樁娈?位銆佹祴璇?Ft銆佹櫘閫氭椿鍔ㄦ寔缁椂闂淬€?
## 4. 鍏」椤圭洰鍙傛暟鍓嶅悗绔紶閫?
鍓嶇鐘舵€?`frontend/src/App.jsx` 涓殑 `project`锛?
- `name`
- `description`
- `reliability_target`
- `readiness_target`
- `simulation_unit`
- `missile_count`

杩愯浠跨湡鏃剁敱 `SimulationPanel` 鍙戦€侊細

```json
{
  "project": { ...鍏」... },
  "simulation_unit": "day",
  "entity_count": 6,
  "simulation_start": 0,
  "simulation_end": 120,
  "random_seed": 2026,
  "evaluation_targets": {
    "overall_reliability_min": 0.6,
    "readiness_min": 0.6
  }
}
```

鍚庣閾捐矾锛?
1. `SimulationConfig` 瑙ｆ瀽 `project`锛屾牎楠?`project.missile_count == entity_count`銆乣project.simulation_unit == simulation_unit`銆?2. `SimulationRuntime._build_result()` 鍐欏叆 `SimulationResult.project` 鍜?`simulation_unit`銆?3. `ExperimentStore.save()` 鍐欏叆 `ExperimentRecord.project`銆?4. `evaluate_simulation()` 鎶婇」鐩彲闈犲害鐩爣鏄犲皠涓?`overall_reliability_min`锛屾妸鎴樺瀹屽ソ搴︾洰鏍囨槧灏勪负 `readiness_min`銆?5. 瀹為獙鍒楄〃杩斿洖 `project_name`锛岀粨鏋滈〉灞曠ず椤圭洰鍚嶇О銆佹弿杩般€佺洰鏍囧拰瀵煎脊鏁伴噺銆?
瀹炴祴璇佹槑锛歚verification/2026-11-26-stage-reliability/web_e2e_summary.json` 涓疄楠岃褰曞寘鍚」鐩悕绉般€佸寮规暟閲?6銆佷豢鐪熷崟浣?day锛屾祴璇曞垪琛?4 涓祴璇曟ā鍧楋紝闃舵鑺傜偣涓?`n_storage`銆乣n_duty`銆?
## 5. 鐢诲竷甯冨眬璋冩暣

宸插仛璋冩暣锛?
- 澧炲ぇ dagre 鐨?`nodesep/ranksep/edgesep`锛屽噺灏戣妭鐐逛笌杩炵嚎鎸ゅ湪涓€璧枫€?- 瀛愭祦绋嬪睍寮€鏃讹紝鑷姩 `fitView` 鍒拌瀛愭祦绋嬬殑鍧楄妭鐐?+ 鍏ㄩ儴鍐呴儴鑺傜偣锛屼繚璇佸唴閮ㄨ妭鐐瑰拰杩炵嚎瀹屾暣鍙銆佸瓧浣撳彲璇汇€?- 鏀惰捣瀛愭祦绋嬪悗鎭㈠澶栧眰鍏ㄥ眬瑙嗗浘銆?- 鏀寔缂╂斁銆佸钩绉汇€丮iniMap銆丆ontrols銆侀€傚簲灞忓箷銆佸睍寮€鍏ㄩ儴銆佹敹璧峰叏閮ㄣ€?- 澶栧眰瑙嗗浘鐨?fit 鏈€灏忕缉鏀捐涓?0.4锛涘睍寮€瀛愭祦绋嬫椂鑱氱劍鍒板瓙娴佺▼锛屾渶灏忕缉鏀?0.55銆?- 鏅€?task 鑺傜偣鏄剧ず鈥滀粎鎸佺画鏃堕棿鈥濓紝闃舵 subprocess 鏄剧ず 位 鐘舵€侊紝娴嬭瘯 task 鏄剧ず娴嬭瘯妯″潡鍜?Ft銆?
鎴浘锛?
- `01_project_and_outer_flow.png`锛氬灞備富娴佺▼鍏ㄥ眬瑙嗗浘銆?- `03_storage_expanded.png`锛氳串瀛樺瓙娴佺▼灞曞紑锛屽唴閮ㄨ妭鐐广€佸垽鏂€佺淮淇洖璺拰杩炵嚎娓呮櫚鍙銆?- `04_duty_expanded.png`锛氬€肩彮瀛愭祦绋嬪睍寮€锛屽唴閮ㄨ妭鐐广€佸惊鐜洖璺竻鏅板彲瑙併€?- `02_simulation_results.png`锛氱湡瀹炰豢鐪熺粨鏋溿€?
閬楃暀鍙栬垗锛氬灞傚叏灞€ fit 涓轰簡鏄剧ず瀹屾暣涓绘祦绋嬩細缂╁緱杈冨皬锛涘睍寮€瀛愭祦绋嬩細鑷姩鑱氱劍锛屽洜姝ゅ唴閮ㄨ妭鐐逛繚鎸佸彲璇汇€傝嫢瑕佹眰鈥滃灞傚叏閮ㄨ妭鐐瑰悓鏃朵繚鎸佸ぇ瀛椾綋鈥濓紝闇€瑕佽繘涓€姝ユ敼鍙樺灞傚竷灞€涓烘崲琛?铔囧舰甯冨眬锛岃绗?13 鑺傘€?
## 6. 位1銆佄? 閰嶇疆涓庤绠楅€昏緫

瑙勮寖娴佺▼涓彧鏈変袱涓樁娈?subprocess锛?
- `n_storage`锛堣串瀛橀樁娈碉級锛氭晠闅滅巼 位1锛岄樁娈典富浠诲姟 `s_store`銆?- `n_duty`锛堝€肩彮闃舵锛夛細鏁呴殰鐜?位2锛岄樁娈典富浠诲姟 `d_duty`銆?
瀹炵幇浣嶇疆锛歚app/simulation/engine.py::_sample_stage_task()`銆?
姣忎釜瀹炰綋銆佹瘡娆¤繘鍏ラ樁娈典富浠诲姟鏃讹細

1. `t` 浠?0 寮€濮嬶紝鎸変豢鐪熷崟浣嶆闀?1 绱姞銆?2. 姣忎竴姝ユ娊鍙?`p(t) 鈭?[0,1]`銆?3. 璁＄畻 `R(t)=exp(-位*t)`銆?4. 鑻?`p(t) > R(t)`锛岃褰曞疄闄呮晠闅滄椂闂村苟鍋滄璇ユ璁块棶鐨勬娊鏍枫€?5. 鑻?`p(t) 鈮?R(t)`锛岀户缁笅涓€姝ャ€?6. 缁翠慨鍚庨噸鏂拌繘鍏ラ樁娈典富浠诲姟鏃讹紝`t` 閲嶆柊浠?0 寮€濮嬨€?7. 鏅€?task 涓嶈繘鍏ヨ鍑芥暟锛屼篃涓嶅仛鎸囨暟鏁呴殰鎶芥牱銆?8. 位 鍗曚綅蹇呴』涓庨」鐩豢鐪熷崟浣嶄竴鑷达紱涓嶄竴鑷存椂 Runtime 杩斿洖 `reliability_lambda_unit_mismatch`銆?
璇ュ疄鐜颁笌鍥剧墖 1 鐨勯€愭椂闂存姣旇緝涓€鑷达紝鑰屼笉鏄棫鐨勨€滄瘡浠诲姟鎶藉彇涓€娆℃晠闅滄椂闂粹€濈殑 `time_to_failure` 鍙ｅ緞銆傛棫鍙ｅ緞浠呬负鏃фā鍨嬪吋瀹逛繚鐣欍€?
## 7. Ft 鏁呴殰妫€娴嬮€昏緫

瀹炵幇浣嶇疆锛歚app/simulation/engine.py::_run_detection()`銆?
姣忎釜娴嬭瘯妯″潡锛坄module_type="test"`锛夊湪娴嬭瘯瀹屾垚鏃讹細

1. 鍙娊鍙栦竴娆?`pt 鈭?[0,1]`銆?2. 鑻ュ綋鍓嶅疄浣撳凡鏁呴殰涓?`pt 鈮?Ft`锛?   - 璁板綍鍙戠幇鏁呴殰锛?   - 鍐欏叆 `test_detected=True`锛?   - 杩涘叆缁翠慨璺緞锛?   - 缁翠慨瀹屾垚鍚庢仮澶?`currently_failed=False`锛?   - 璁板綍鍙戠幇鏃堕棿銆佺淮淇紑濮?缁撴潫鏃堕棿銆?3. 鑻ュ綋鍓嶅疄浣撳凡鏁呴殰涓?`pt > Ft`锛?   - 璁板綍鏈彂鐜版晠闅滐紱
   - 涓嶇淮淇紱
   - 淇濇寔鏁呴殰鐘舵€侊紱
   - 涓嶅彲鐢ㄦ椂闂翠粠瀹為檯鏁呴殰鍙戠敓鏃堕棿鎸佺画绱銆?4. 鑻ュ綋鍓嶅疄浣撴湭鏁呴殰锛氭祴璇曢€氳繃锛屼笉浜х敓缁翠慨銆?
娴嬭瘯妯″潡鍙傛暟涓庢晠闅滅巼鍙傛暟鍒嗗紑瀛樺偍锛?
- 闃舵锛歚module_type="stage"`锛宍lambda`锛宍lambda_unit`锛宍stage_task_id`銆?- 娴嬭瘯锛歚module_type="test"`锛宍detection_rate`锛團t锛夛紝`test_time`锛沗lambda` 蹇呴』涓虹┖銆?- 鏅€氭椿鍔細`module_type="activity"`锛屼笉鍙備笌鐙珛鏁呴殰鎶芥牱銆?
瑙勮寖娴佺▼涓殑鍥涗釜娴嬭瘯妯″潡锛?
- `s_inspect`锛堣串瀛樻娴嬶級
- `n_first_test`锛堢涓€娆℃祴璇曪級
- `n_second_test`锛堢浜屾娴嬭瘯锛?- `d_inspect`锛堝€肩彮妫€娴嬶級

鍚庣姝ｅ紡鎺ュ彛涔熸墽琛?`check_simulation_readiness()`锛坄app/simulation/readiness.py`锛夛細
璐瓨/鍊肩彮瀛愭祦绋嬬己灏戦樁娈?位銆佹祴璇曡妭鐐圭己灏?Ft銆佹櫘閫氭椿鍔ㄧ己灏戞寔缁椂闂存椂锛?`/experiments` 鍜?`/simulate/evaluate` 浼氳繑鍥?`simulation_parameters_missing`锛?涓嶄細闈欓粯浣跨敤榛樿鍊笺€備綆灞?`/simulate` 淇濈暀鏃у吋瀹硅涓恒€?
## 8. 涓庝袱寮犲浘鐗囩殑绠楁硶涓€鑷存€?
### 鍥剧墖 1

鍥剧墖鍘熸枃鏍稿績锛?
- 璐瓨闃舵绗?`t` 鏃跺埢 `R_s=e^{-位1 t}`銆?- 鍊肩彮闃舵绗?`t` 鏃跺埢 `R_w=e^{-位2 t}`銆?- 姣忎釜鏃跺埢鎶藉彇 `p(t)`锛沗p(t) 鈮?R` 淇濇寔姝ｅ父锛宍p(t) > R` 鍙戠敓鏁呴殰銆?
瀹炵幇涓€鑷达細`_sample_stage_task()` 閫愭鎶藉彇骞朵笌绱 `R(t)` 姣旇緝銆?
闇€瑕佹槑纭殑缁熻鍙ｅ緞锛氱敱浜庢瘡涓€姝ラ兘閲嶆柊鎶藉彇锛宍n` 姝ュ悗鐨勬棤鏁呴殰姒傜巼鏄悇姝?`R(t)` 鐨勪箻绉細

```text
prod_{t=1..n} exp(-位t) = exp(-位 n(n+1)/2)
```

鑰屼笉鏄崟娆?`exp(-位n)`銆傛湰娆′弗鏍兼寜鍥剧墖瀹炵幇锛屾病鏈夋搮鑷浛鎹㈢畻娉曘€傚疄娴嬭绗?9 鑺傦細

- 位=0.001/澶┿€佽串瀛?30 澶┿€?00 瀹炰綋銆丗t=0锛?  - 缁忛獙璐瓨鏁呴殰姣斾緥锛?.3600
  - 閫愭椂闂存涔樼Н鐞嗚锛?.3719
  - 鍗曟 `exp(-位t)` 鐞嗚锛?.0296

杩欒瘉鏄庡綋鍓嶅疄鐜扮鍚堝浘鐗囩殑閫愭椂闂存姣旇緝鍙ｅ緞锛屼絾涓庘€滃崟涓寚鏁板垎甯冧竴娆℃娊鏍封€濈殑鐩磋鍙ｅ緞瀛樺湪鏄捐憲宸紓銆傝宸紓闇€瑕佸湪涓氬姟涓婄‘璁わ紱浠ｇ爜娌℃湁闈欓粯鏇挎崲銆?
### 鍥剧墖 2

鍥剧墖鍘熸枃鏍稿績锛?
- 妫€娴?娴嬭瘯闃舵浣跨敤娴嬭瘯妯″潡鍜?Ft銆?- 姣忔娴嬭瘯鍙娊鍙栦竴涓?`pt` 骞朵笌 Ft 姣旇緝銆?- `pt 鈮?Ft` 鍙戠幇鏁呴殰锛岃繘鍏ョ淮淇紝缁翠慨鏃堕棿璁颁负涓嶅彲鐢紝缁翠慨鍚庤浆涓哄彲鐢ㄣ€?- `pt > Ft` 鏈彂鐜帮紝涓嶇淮淇紝缁х画娴佺▼锛屼笉鍙敤鏃堕棿浠庡疄闄呮晠闅滄椂闂存寔缁褰曘€?- 娴嬭瘯鏃堕棿鍙傛暟瀛樺湪锛屼絾娴嬭瘯鏃堕棿鍐呭彧鎶藉彇涓€娆°€?
瀹炵幇涓€鑷达細`_run_detection()` 姣忔娴嬭瘯瀹屾垚鍙娊鍙栦竴娆★紱鍙戠幇/鏈彂鐜板垎鏀€佺淮淇拰涓嶅彲鐢ㄦ椂闂磋褰曞潎涓庡浘鐗囦竴鑷淬€?
## 9. 鍏粍鏁呴殰鐜囧疄娴嬬粨鏋?
鍥哄畾鏉′欢锛氭瘡缁?200 涓疄浣擄紝浠跨湡绐楀彛 120 澶╋紝闅忔満绉嶅瓙 2026锛屼豢鐪熷崟浣嶅ぉ锛孎t=0.5銆?
| 缁?| 位1(璐瓨) | 位2(鍊肩彮) | 鎬绘晠闅?| 璐瓨鏁呴殰 | 鍊肩彮鏁呴殰 | 宸叉娴?| 宸茬淮淇?| 鏇炬晠闅滃疄浣?| 浣跨敤鍙潬搴?| 鎴樺瀹屽ソ搴?| 涓嶅彲鐢ㄦ椂闂?|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 | 0.0 |
| B | 0.001 | 0.001 | 128 | 102 | 26 | 118 | 118 | 96 | 0.520 | 0.920 | 1926.0 |
| C | 0.01 | 0.01 | 568 | 360 | 208 | 517 | 511 | 200 | 0.000 | 0.556 | 10647.0 |
| D | 0.05 | 0.05 | 968 | 373 | 595 | 851 | 843 | 200 | 0.000 | 0.308 | 16603.0 |
| E | 0.01 | 0.05 | 953 | 360 | 593 | 837 | 825 | 200 | 0.000 | 0.414 | 14072.0 |
| F | 0.05 | 0.001 | 399 | 373 | 26 | 372 | 372 | 200 | 0.000 | 0.516 | 11618.0 |

瓒嬪娍鍒ゆ柇锛?
- A 鏃犳晠闅滃熀绾挎垚绔嬨€?- B鈫扖鈫扗 鎬绘晠闅滄暟闅?位 澧炲ぇ鑰屽鍔犮€?- E 鐨勫€肩彮鏁呴殰锛?93锛夋槑鏄惧ぇ浜庤串瀛樻晠闅滐紙360锛夛紝绗﹀悎 位2 > 位1銆?- F 鐨勮串瀛樻晠闅滐紙373锛夋槑鏄惧ぇ浜庡€肩彮鏁呴殰锛?6锛夛紝绗﹀悎 位1 > 位2銆?- 鎴樺瀹屽ソ搴﹂殢鏁呴殰鐜囦笂鍗囪€屼笅闄嶏紙A 1.000 鈫?B 0.920 鈫?C 0.556 鈫?D 0.308锛夈€?- D 涓?F 鐨勮串瀛樻晠闅滄暟鎺ヨ繎锛岃鏄庤串瀛橀樁娈靛悓鏃跺彈 位1 鎺у埗锛汥 涓?E 鐨勫€肩彮鏁呴殰鏁版帴杩戯紝璇存槑鍊肩彮闃舵鍚屾椂鍙?位2 鎺у埗銆?- 位1/位2 鍙奖鍝嶅搴旈樁娈电殑鏁呴殰璁板綍锛欵/F 鐨勫垎闃舵缁熻璇佹槑浜嗚繖涓€鐐广€?
澶氶殢鏈虹瀛愬鏍革紙姣忕粍 80 瀹炰綋銆?20 澶╋紝楠岃瘉 A鈮鈮鈮 鐨勬€绘晠闅滆秼鍔匡級锛?
| 绉嶅瓙 | A | B | C | D |
|---:|---:|---:|---:|---:|
| 1 | 0 | 56 | 223 | 386 |
| 7 | 0 | 49 | 226 | 374 |
| 2026 | 0 | 47 | 236 | 380 |

淇濆瓨鏂囦欢锛歚verification/2026-11-26-stage-reliability/matrix_report.md`銆乣matrix_results.json`銆?
## 10. 妫€娴嬬巼 Ft 瀹炴祴缁撴灉

鍥哄畾鏉′欢锛毼?=0.002锛屛?=0锛?00 瀹炰綋锛?40 澶╋紝绉嶅瓙 77锛孎t=0/0.5/1銆?
| Ft | 鎬绘晠闅?| 宸叉娴?| 宸茬淮淇?| 褰撳墠鏁呴殰瀹炰綋 | 娴嬭瘯鏈夋晠闅滄鏁?| 妫€鍑烘鏁?| 妫€鍑洪鐜?| 鎴樺瀹屽ソ搴?|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0 | 112 | 0 | 0 | 112 | 4032 | 0 | 0.0 | 0.483 |
| 0.5 | 179 | 179 | 179 | 0 | 347 | 179 | 0.5159 | 0.931 |
| 1.0 | 244 | 244 | 244 | 0 | 244 | 244 | 1.0 | 0.926 |

缁撹锛?
- Ft=0锛氭病鏈変换浣曟晠闅滆鍙戠幇锛屾病鏈夌淮淇紝鏁呴殰瀹炰綋淇濇寔鏁呴殰锛屾垬澶囧畬濂藉害鏈€浣庛€?- Ft=1锛氭祴璇曟椂鏈夋晠闅滅殑娴嬭瘯鍏ㄩ儴鍙戠幇骞剁淮淇紝褰撳墠鏁呴殰瀹炰綋涓?0銆?- Ft=0.5锛氭鍑洪鐜囩害 0.516锛屾帴杩戣瀹氬€笺€?- Ft 鏀瑰彉鐨勬槸鈥滃彂鐜版鐜団€濆拰鍚庣画缁翠慨/鍙敤鏃堕棿锛涘悓涓€闅忔満绉嶅瓙涓嬶紝瀹炰綋鐨勯娆″疄闄呮晠闅滄椂闂翠笉鍥?Ft 鏀瑰彉锛岃鏄?Ft 娌℃湁鏀瑰彉瀹為檯鏁呴殰鍙戠敓姒傜巼銆?- 鐢变簬 Ft=0 鏃舵湭缁翠慨鐨勬晠闅滀細鎸佺画瀛樺湪锛屽悗缁祴璇曚粛鍙兘鍐嶆妫€娴嬶紱琛ㄤ腑鐨勨€滄鍑洪鐜団€濇寜鈥滄祴璇曟椂鏈夋晠闅溾€濈殑娴嬭瘯娆℃暟缁熻锛岃€屼笉鏄寜鏈€缁堟晠闅滆褰曠粺璁°€?
## 11. 鍙潬搴︺€佹垬澶囧畬濂藉害銆佸彲鐢?涓嶅彲鐢ㄦ椂闂寸粺璁?
- 瑁呭浣跨敤鍙潬搴︼細`overall_reliability = 1 - ever_failed_entity_count / entity_count`銆?- 鎴樺瀹屽ソ搴︼細`readiness = total_available_time / (entity_count * simulation_horizon)`銆?- 鍙敤鏃堕棿锛歚available_time = horizon - unavailable_time`銆?- 涓嶅彲鐢ㄦ椂闂达細浠庡疄闄呮晠闅滃彂鐢熸椂闂村紑濮嬶紝鍒扮淮淇畬鎴愭椂闂达紱鏈慨澶嶅垯鎸佺画鍒颁豢鐪熺粨鏉熴€?- 鏁呴殰璁板綍鍖呭惈锛氭晠闅滃彂鐢熸椂闂淬€佸彂鐜版椂闂淬€佸彂鐜拌妭鐐广€佹娴嬮殢鏈烘暟銆丗t銆佺淮淇紑濮嬨€佺淮淇粨鏉熴€佹槸鍚︿慨澶嶃€佷笉鍙敤鏃堕棿銆佹槸鍚﹀湪缁撴潫鏃朵粛寮€鏀俱€?- 娴嬭瘯璁板綍鍖呭惈锛氭祴璇曡妭鐐广€佹椂闂淬€丗t銆侀殢鏈烘暟銆佹祴璇曞墠鏄惁鏈夋晠闅溿€佹槸鍚﹀彂鐜般€佹晠闅滄椂闂淬€佹祴璇曟椂闂淬€?
瀹炴祴涓墍鏈夊疄浣撳潎婊¤冻锛?
```text
available_time + unavailable_time == simulation_end - simulation_start
```

## 12. 鐪熷疄缃戦〉杩愯缁撴灉

浣跨敤鐪熷疄 FastAPI 鏈嶅姟 + 瀹為檯鏋勫缓浜х墿 `web/` + Microsoft Edge 鏃犲ご娴忚鍣紙Playwright锛夛細

鑴氭湰锛歚verification/2026-11-26-stage-reliability/web_e2e.py`  
缁撴灉锛歚verification/2026-11-26-stage-reliability/web_e2e_summary.json`

缁撴灉锛?*23/23 鏂█閫氳繃**锛屽寘鎷細

- 鍏」椤圭洰鍙傛暟杈撳叆鍖哄煙娓叉煋銆?- 鏈～鍐欓」鐩弬鏁版椂鈥滄墦寮€浠跨湡杩愯鈥濈鐢ㄣ€?- 濉啓瀹屾暣鍚庡惎鐢ㄣ€?- 缂哄皯闃舵 位 / 娴嬭瘯 Ft 鏃惰繍琛屾寜閽鐢紝骞舵彁绀虹己灏戝弬鏁般€?- 閫氳繃 subprocess 鍙充晶 位 鍙傛暟鎸夐挳閰嶇疆璐瓨 位=0.002銆佸€肩彮 位=0.005銆?- 位 鍗曚綅鏍囩鏄剧ず鈥滄瘡澶┾€濄€?- 鏅€氭椿鍔ㄦ病鏈?位 杈撳叆妗嗭紝鍙樉绀烘寔缁椂闂淬€?- 鍥涗釜娴嬭瘯妯″潡閰嶇疆 Ft=0.8銆佹祴璇曟椂闂?1銆?- 琛ラ綈鍙傛暟鍚庤繍琛屾寜閽惎鐢ㄣ€?- 缃戦〉鐪熷疄杩愯骞舵樉绀烘垬澶囧畬濂藉害銆佹祴璇曟ā鍧楁娴嬫寚鏍囥€侀」鐩悕绉板拰鐩爣銆?- 瀹為獙缁撴灉鎸佷箙鍖栵紝椤圭洰鍚嶇О銆佸寮规暟閲?6銆? 涓祴璇曟ā鍧椼€佷袱涓樁娈佃妭鐐瑰潎鍙拷婧€?
鐪熷疄杩愯缁撴灉鎽樿锛?
- 椤圭洰锛氭煇鍨嬪寮硅串瀛樺€肩彮淇濋殰椤圭洰
- 瀵煎脊鎬绘暟閲忥細6
- 浠跨湡鍗曚綅锛氬ぉ
- 鎬绘晠闅滐細10
- 鎴樺瀹屽ソ搴︼細0.8972
- 瑁呭浣跨敤鍙潬搴︼細0.1667
- 娴嬭瘯妯″潡锛歚s_inspect`銆乣n_first_test`銆乣n_second_test`銆乣d_inspect`
- 闃舵鑺傜偣锛歚n_storage`锛埼?0.002/澶╋級銆乣n_duty`锛埼?0.005/澶╋級

鎴浘锛?
- `01_project_and_outer_flow.png`
- `03_storage_expanded.png`
- `04_duty_expanded.png`
- `02_simulation_results.png`

Web 楠岃瘉浣跨敤闅旂鐨勪复鏃舵暟鎹洰褰曪紙`verification/2026-11-26-stage-reliability/run_data`锛夛紝娌℃湁淇敼姝ｅ紡 `data/processes`銆乣data/reliability`銆乣data/experiments`銆?
## 13. 灏氭湭瑙ｅ喅鐨勯棶棰樹笌闇€瑕佺‘璁や簨椤?
1. **鍥剧墖 1 閫愭椂闂存鎶芥牱鐨勭粺璁″彛寰?*
   - 褰撳墠涓ユ牸鎸夊浘鐗囧疄鐜帮細姣忔閲嶆柊鎶藉彇 `p(t)` 骞朵笌绱 `R(t)` 姣旇緝銆?   - 鍏舵暟瀛﹀悗鏋滄槸鏃犳晠闅滄鐜囦负 `exp(-位 n(n+1)/2)`锛岄珮 位 涓嬫晠闅滄鐜囪繙楂樹簬鍗曟鎸囨暟鎶芥牱銆?   - 瀹炴祴锛毼?0.001銆?0 澶╂椂锛岀粡楠屾晠闅滄瘮渚?0.3600锛岀鍚?0.3719 鐨勯€愭椂闂存鐞嗚锛岃€屼笉鏄?0.0296 鐨勫崟娆℃寚鏁扮悊璁恒€?   - 闇€瑕佷笟鍔＄‘璁わ細鏄繚鐣欏浘鐗囩殑閫愭姣旇緝鍙ｅ緞锛岃繕鏄敼涓衡€滄瘡涓樁娈靛彧鎶藉彇涓€娆℃晠闅滄椂闂粹€濈殑鎸囨暟鍒嗗竷鍙ｅ緞銆備唬鐮佹病鏈夋搮鑷浛鎹€?
2. **楂?位 瀵艰嚧璐瓨缁翠慨寰幆**
   - 鐢变簬閫愭椂闂存鍙ｅ緞鍦ㄩ珮 位 涓嬪嚑涔庡繀鐒跺湪璐瓨闃舵鏁呴殰锛岃嫢 Ft 杈冮珮锛屽疄浣撳彲鑳藉湪璐瓨鈥旂淮淇€斿啀璐瓨涔嬮棿寰幆鍒颁豢鐪熺粨鏉熴€?   - 杩欐槸鍥剧墖绠楁硶鍜屼笟鍔℃祦绋嬪叡鍚屼綔鐢ㄧ殑缁撴灉锛屼笉鏄?Runtime 姝诲惊鐜紱Runtime 浠嶅彈浜嬩欢鏁般€佽闂鏁板拰浠跨湡缁堟鏃堕棿闄愬埗銆?   - 闇€瑕佷笟鍔＄‘璁ら珮 位 鍦烘櫙鏄惁鍏佽杩欑鎸佺画缁翠慨寰幆銆?
3. **鍊肩彮鎸佺画寰幆鐨勭粓姝?*
   - 鍊肩彮姝ｅ父鍚庢寜闇€姹傜户缁笅涓€杞€肩彮锛屾病鏈夊鍔犱换鍔℃湡婊℃垨杩旀腐绛変笟鍔℃椿鍔ㄣ€?   - 瑙勮寖娴佺▼鍐呴儴浣跨敤 `node_visits.d_duty < 1_000_000` 浣滀负鎶€鏈惊鐜嚭鍙ｏ紝骞朵繚鐣欑粨鏋?end锛屾甯歌繍琛岀敱浠跨湡缁堟鏃堕棿缁撴潫銆?   - 杩欎笉鏄笟鍔℃湡婊℃潯浠讹紱濡傛灉鐢ㄦ埛瑕佹眰娌℃湁鍏ㄥ眬浠跨湡缁堟鏃堕棿锛孯untime 鏃犳硶鑷劧缁撴潫銆?
4. **浠跨湡鍗曚綅涓殑鈥滄湀/骞粹€?*
   - 褰撳墠鎶婃湀/骞翠綔涓轰豢鐪熸椂闂村崟浣嶄娇鐢紝位 涓烘瘡鏈?姣忓勾锛屾湭鍋?30 澶?365 澶╃殑鏃ュ巻鎹㈢畻銆?   - 濡傛灉涓氬姟瑕佹眰鑷劧鏈?鏃ュ巻骞存崲绠楋紝闇€瑕佽繘涓€姝ョ‘璁ゃ€?
5. **椤圭洰鍙傛暟鎸佷箙鍖栦綅缃?*
   - 褰撳墠椤圭洰鍙傛暟淇濆瓨鍦ㄥ墠绔?localStorage锛屽苟闅忔寮忓疄楠岃褰曟寔涔呭寲锛涙病鏈夊啓鍏?Process IR銆?   - 濡傛灉瑕佹眰椤圭洰鍙傛暟闅?Process IR 鐗堟湰涓€璧风増鏈寲锛岄渶瑕佹柊澧炵嫭绔嬮」鐩弬鏁板瓨鍌ㄦ垨鎵╁睍 Process IR Schema銆?
6. **鏃фā鍨嬪吋瀹?*
   - 鏃х増 task 绾?位 浠嶇劧琚?Runtime 鏀寔锛屼互渚挎棫妯″瀷鍙互缁х画杩愯锛涗絾鏂?UI 涓嶅啀涓烘櫘閫?task 鎻愪緵 位 杈撳叆銆?   - 鏃фā鍨嬪鏋滃笇鏈涗娇鐢ㄦ柊鐨勯樁娈?位/娴嬭瘯 Ft 鏈哄埗锛岄渶瑕侀噸鏂颁繚瀛樹负 stage/test 閰嶇疆銆?
7. **娴嬭瘯鑺傜偣璇嗗埆**
   - UI 浼氭寜鑺傜偣鍚嶇О涓殑鈥滄祴璇?妫€娴嬧€濊嚜鍔ㄥ缓璁祴璇曟ā鍧楋紱涔熷彲浠ユ墜鍔ㄥ垏鎹负娴嬭瘯妯″潡鎴栨櫘閫氭椿鍔ㄣ€?   - 濡傛灉娴嬭瘯鑺傜偣鍛藉悕涓嶈鑼冿紝闇€瑕佺敤鎴锋墜鍔ㄦ爣璁般€?
8. **鐢诲竷澶栧眰鍏ㄥ眬瑙嗗浘**
   - 瀛愭祦绋嬪睍寮€鏃朵細鑷姩鑱氱劍鍒板唴閮ㄨ妭鐐癸紝鍐呴儴鑺傜偣鍜岃繛绾垮畬鏁村彲璇汇€?   - 澶栧眰鍏ㄥ眬 fit 涓轰簡鏄剧ず瀹屾暣涓绘祦绋嬩細缂╁緱杈冨皬锛涘鏋滆姹傚灞傛墍鏈夎妭鐐瑰悓鏃朵繚鎸佸ぇ瀛椾綋锛岄渶瑕佹敼涓烘崲琛?铔囧舰甯冨眬锛岃繖浼氭敼鍙樼幇鏈変粠宸﹀埌鍙冲竷灞€涔犳儻銆?
9. **鎴樺瀹屽ソ搴︾殑鏃堕棿鍙ｅ緞**
   - 褰撳墠鎸夊畬鏁翠豢鐪熺獥鍙ｇ粺璁″彲鐢?涓嶅彲鐢ㄦ椂闂达紝宸插畬鎴愬疄浣撳湪瀹屾垚鍚庝粛鎸夊彲鐢ㄦ椂闂磋鍏ャ€?   - 濡傛灉闇€瑕佹寜鈥滆澶囧疄闄呭湪褰规椂闂粹€濈粺璁★紝闇€瑕佷笟鍔＄‘璁ゃ€?
10. **姝ｅ紡 API 涓庡吋瀹?API**
    - 姝ｅ紡瀹為獙鎺ュ彛 `/api/processes/{id}/experiments` 寮哄埗瑕佹眰椤圭洰鍙傛暟銆?    - 浣庡眰 `/api/processes/{id}/simulate` 浠嶄繚鎸佹棫鍏煎锛屼笉寮哄埗椤圭洰鍙傛暟锛沇eb 涓嶅湪浣跨敤璇ヤ綆灞傛帴鍙ｃ€?
## 14. 娴嬭瘯涓庢瀯寤哄懡浠?
```powershell
# 鍚庣
.\.venv\Scripts\python.exe -m pytest
# 289 passed

# 鍓嶇
cd frontend
npm test
# 35 passed

# 鏋勫缓鐪熷疄 Web 浜х墿
npm run build
# 杈撳嚭鍒?..\web

# 鍏粍鏁呴殰鐜?妫€娴嬬巼瀹炴祴
cd ..
.\.venv\Scripts\python.exe verification\2026-11-26-stage-reliability\run_matrix.py

# 鐪熷疄 Web E2E锛圗dge + Playwright锛?.\.venv\Scripts\python.exe verification\2026-11-26-stage-reliability\web_e2e.py
```

## 15. 涓昏娴嬭瘯鏂囦欢

- `tests/test_stage_reliability_runtime.py`锛?6 涓樁娈?妫€娴?鏃堕棿璁板綍/鍗曚綅/椤圭洰杩芥函娴嬭瘯銆?- `tests/test_multi_group_reliability.py`锛欰-F 鍏粍瓒嬪娍鍜?Ft 瀵圭収銆?- `tests/test_project_simulation_api.py`锛氶」鐩弬鏁板己鍒躲€佸疄楠屾寔涔呭寲銆侀樁娈?娴嬭瘯鎸囨爣銆?- `tests/test_nested_process.py`銆乣tests/test_nested_api.py`锛氭棫宓屽娴佺▼鍏煎銆?- `frontend/tests/project.test.mjs`銆乣reliability.test.mjs`銆乣simulation.test.mjs`銆乣nested.test.mjs`銆?
