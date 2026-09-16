# Task 9 Verification Report

Date: 2026-09-06

## Documentation changes

Updated the three requested documentation files to define workspace-first ownership, fixed tabs, permanent workspace panels, provenance, owner-scoped 404 protections, chat-scoped research positions (explicitly not connected-wallet live positions), and the mock trading-ticket boundary.

## Backend verification

Exact commands: `alembic heads`; `alembic current`; `pytest tests/test_research_migration.py tests/test_research_repository.py tests/test_research_api.py -q`

```text
a0b1c2d3e4f5 (head)
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
a0b1c2d3e4f5 (head)
......................................                                   [100%]
38 passed in 37.99s

```

Result: PASS. One Alembic head (`a0b1c2d3e4f5`), current database at that head, 38 focused tests passed. The available migration test harness exercised the current database state and its legacy-row/provenance assertions, but it did not provide a separate empty-database migration invocation or a rerun/idempotency invocation in this task. Those two scenarios were not independently performed; the report does not claim them as verified.

## Frontend verification

### `npm test`

```text

> frontend@0.1.0 test
> vitest run


[1m[46m RUN [49m[22m [36mv3.2.7 [39m[90mD:/project/poly/frontend[39m

(node:28344) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:34748) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:17368) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:7948) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:29968) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:39100) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:13252) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:2788) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:20412) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:37316) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:1328) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
(node:39548) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
 [32mâœ“[39m src/components/research/__tests__/panelGeometry.test.ts [2m([22m[2m5 tests[22m[2m)[22m[32m 12[2mms[22m[39m
 [32mâœ“[39m src/hooks/usePanelLayout.test.tsx [2m([22m[2m6 tests[22m[2m)[22m[32m 67[2mms[22m[39m
 [32mâœ“[39m src/utils/researchApi.test.ts [2m([22m[2m9 tests[22m[2m)[22m[32m 46[2mms[22m[39m
 [32mâœ“[39m src/hooks/useResearchHub.test.tsx [2m([22m[2m6 tests[22m[2m)[22m[33m 477[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/PanelInteraction.test.tsx [2m([22m[2m5 tests[22m[2m)[22m[33m 454[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/CanvasTabs.test.tsx [2m([22m[2m2 tests[22m[2m)[22m[33m 554[2mms[22m[39m
   [33m[2mâœ“[22m[39m CanvasTabs[2m > [22mrenders only fixed tabs, selection, and keyboard activation [33m 496[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/TradingPanel.test.tsx [2m([22m[2m5 tests[22m[2m)[22m[33m 675[2mms[22m[39m
   [33m[2mâœ“[22m[39m TradingPanel (Mock Order Ticket)[2m > [22mhas a 'Review mock order' button that never calls fetch or submits an order [33m 391[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/WorkspaceSelector.test.tsx [2m([22m[2m1 test[22m[2m)[22m[33m 990[2mms[22m[39m
   [33m[2mâœ“[22m[39m WorkspaceSelector[2m > [22mselects, creates, renames, and requests deletion accessibly [33m 988[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/ChatTabs.test.tsx [2m([22m[2m7 tests[22m[2m)[22m[33m 1202[2mms[22m[39m
   [33m[2mâœ“[22m[39m ChatTabs[2m > [22mselects a tab on click and marks it selected [33m 338[2mms[22m[39m
   [33m[2mâœ“[22m[39m ChatTabs[2m > [22mrenames inline with Enter [33m 360[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/PositionsBar.test.tsx [2m([22m[2m6 tests[22m[2m)[22m[33m 1086[2mms[22m[39m
   [33m[2mâœ“[22m[39m PositionsBar[2m > [22mrenders real position row and handles selection [33m 592[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/ChatRail.test.tsx [2m([22m[2m9 tests[22m[2m)[22m[33m 1659[2mms[22m[39m
   [33m[2mâœ“[22m[39m ChatRail[2m > [22msubmits on Enter and clears the composer [33m 645[2mms[22m[39m
   [33m[2mâœ“[22m[39m ChatRail[2m > [22madds a newline on Shift+Enter without submitting [33m 361[2mms[22m[39m
   [33m[2mâœ“[22m[39m ChatRail[2m > [22menables composer and submits prompt even when chatId is null for auto-creation [33m 398[2mms[22m[39m
 [32mâœ“[39m src/components/research/__tests__/PanelCanvas.test.tsx [2m([22m[2m13 tests[22m[2m)[22m[33m 1707[2mms[22m[39m
   [33m[2mâœ“[22m[39m PanelCanvas[2m > [22mmaps every panel type through the exhaustive renderer [33m 473[2mms[22m[39m
   [33m[2mâœ“[22m[39m PanelCanvas[2m > [22mpreserves active geometry when the parent chat changes within a workspace [33m 332[2mms[22m[39m

[2m Test Files [22m [1m[32m12 passed[39m[22m[90m (12)[39m
[2m      Tests [22m [1m[32m74 passed[39m[22m[90m (74)[39m
[2m   Start at [22m 21:23:50
[2m   Duration [22m 7.59s[2m (transform 2.18s, setup 11.11s, collect 7.50s, tests 8.93s, environment 34.87s, prepare 2.74s)[22m


```

Result: PASS (12 files, 74 tests).

### `npm run lint`

```text

> frontend@0.1.0 lint
> eslint


D:\project\poly\frontend\next.config.ts
  4:3  error  Use "@ts-expect-error" instead of "@ts-ignore", as "@ts-ignore" will do nothing if the following line is error-free  @typescript-eslint/ban-ts-comment

D:\project\poly\frontend\src\app\agents\AgentBuilder.tsx
  70:19  error  Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\app\agents\page.tsx
  10:40  error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          @typescript-eslint/no-explicit-any
  11:54  error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          @typescript-eslint/no-explicit-any
  32:7   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\agents\page.tsx:32:7
  30 |   useEffect(() => {
  31 |     if (!token) {
> 32 |       setLoading(false);
     |       ^^^^^^^^^^ Avoid calling setState() directly within an effect
  33 |       return;
  34 |     }
  35 |     fetchAll();  react-hooks/set-state-in-effect
  38:6   warning  React Hook useEffect has a missing dependency: 'fetchAll'. Either include it or remove the dependency array                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       react-hooks/exhaustive-deps

D:\project\poly\frontend\src\app\dashboard\AddWalletsPanel.tsx
   4:28  warning  'Trash2' is defined but never used        @typescript-eslint/no-unused-vars
   4:62  warning  'Sparkles' is defined but never used      @typescript-eslint/no-unused-vars
  37:19  error    Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any
  84:19  error    Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\app\dashboard\WatchlistSnapshot.tsx
  3:8  warning  'Link' is defined but never used  @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\app\dashboard\page.tsx
   7:32  warning  'formatCurrency' is defined but never used     @typescript-eslint/no-unused-vars
  10:10  warning  'WatchlistSnapshot' is defined but never used  @typescript-eslint/no-unused-vars
  23:40  error    Unexpected any. Specify a different type       @typescript-eslint/no-explicit-any
  47:80  error    Unexpected any. Specify a different type       @typescript-eslint/no-explicit-any
  58:38  error    Unexpected any. Specify a different type       @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\app\feed\page.tsx
   6:8   warning  'Link' is defined but never used        @typescript-eslint/no-unused-vars
  19:10  warning  'tierNumber' is defined but never used  @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\app\loading.tsx
  1:24  warning  'SkeletonRow' is defined but never used       @typescript-eslint/no-unused-vars
  1:37  warning  'SkeletonStatCard' is defined but never used  @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\app\tools\wallet-tracker\page.tsx
  36:17  error  Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any
  93:19  error  Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\app\tracker\page.tsx
   5:8   warning  'Link' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           @typescript-eslint/no-unused-vars
  43:10  warning  'loading' is assigned a value but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-unused-vars
  71:21  error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\tracker\page.tsx:71:21
  69 |   }, [selectedListId]);
  70 |
> 71 |   useEffect(() => { fetchLists(); }, [fetchLists]);
     |                     ^^^^^^^^^^ Avoid calling setState() directly within an effect
  72 |   useEffect(() => { fetchWallets(); }, [fetchWallets]);
  73 |
  74 |   const handleCreateList = async () => {                 react-hooks/set-state-in-effect
  72:21  error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\tracker\page.tsx:72:21
  70 |
  71 |   useEffect(() => { fetchLists(); }, [fetchLists]);
> 72 |   useEffect(() => { fetchWallets(); }, [fetchWallets]);
     |                     ^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  73 |
  74 |   const handleCreateList = async () => {
  75 |     if (!newListName.trim()) return;  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\app\wallet\[address]\page.tsx
    36:41   warning  'timeAgo' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    @typescript-eslint/no-unused-vars
    43:10   warning  'KpiCardStrip' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-unused-vars
    55:30   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
    84:37   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   274:51   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   365:44   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   435:38   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   436:42   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   437:62   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   438:48   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   439:40   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   440:46   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   441:58   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   442:56   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   443:50   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   444:54   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   496:10   warning  'lineageLoading' is assigned a value but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    @typescript-eslint/no-unused-vars
   589:13   error    'finalOpen' is never reassigned. Use 'const' instead                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   prefer-const
   590:13   error    'finalClosed' is never reassigned. Use 'const' instead                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 prefer-const
   663:5    error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\wallet\[address]\page.tsx:663:5
  661 |     if (!address) return;
  662 |     loadedTabsRef.current.clear();
> 663 |     setStats(null);
      |     ^^^^^^^^ Avoid calling setState() directly within an effect
  664 |     setCategories([]);
  665 |     setPositions([]);
  666 |     setClosedPositions([]);  react-hooks/set-state-in-effect
   700:6    warning  React Hook useEffect has missing dependencies: 'activeTab', 'loadCategories', 'loadClosedPositions', 'loadLineage', 'loadOpenPositions', 'loadParlays', 'loadReconciliation', 'loadStats', and 'loadTrades'. Either include them or remove the dependency array                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        react-hooks/exhaustive-deps
   788:25   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   836:28   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   838:28   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   841:28   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   851:28   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
   985:25   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
  1105:50   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
  1109:96   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
  1192:9    warning  'avgBuyPrice' is assigned a value but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       @typescript-eslint/no-unused-vars
  1584:72   error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any
  1584:187  error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\app\wallets\page.tsx
   12:10  warning  'WalletTable' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         @typescript-eslint/no-unused-vars
  120:24  warning  'setSourceFilter' is assigned a value but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            @typescript-eslint/no-unused-vars
  176:7   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\wallets\page.tsx:176:7
  174 |   useEffect(() => {
  175 |     if (category === "OVERALL") {
> 176 |       setSubcategoryOptions([]);
      |       ^^^^^^^^^^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  177 |       setFilterSubcategory("");
  178 |       setLeagueOptions([]);
  179 |       setFilterLeague("");                                                                                 react-hooks/set-state-in-effect
  200:7   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\wallets\page.tsx:200:7
  198 |   useEffect(() => {
  199 |     if (category === "OVERALL" || !filterSubcategory) {
> 200 |       setLeagueOptions([]);
      |       ^^^^^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  201 |       setFilterLeague("");
  202 |       return;
  203 |     }                                                                                                             react-hooks/set-state-in-effect
  217:5   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\app\wallets\page.tsx:217:5
  215 |   // Reset paging/sort only when the main tab changes (All / Curated / Standard / etc.)
  216 |   useEffect(() => {
> 217 |     setSortField(DEFAULT_SORT[tab].field);
      |     ^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  218 |     setSortOrder(DEFAULT_SORT[tab].order);
  219 |     setParlaySortField("parlay_pnl");
  220 |     setParlaySortOrder("desc");  react-hooks/set-state-in-effect
  274:9   warning  'columns' is assigned a value but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    @typescript-eslint/no-unused-vars
  601:6   warning  React Hook useMemo has a missing dependency: 'handleTradeSort'. Either include it or remove the dependency array                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                react-hooks/exhaustive-deps

D:\project\poly\frontend\src\components\AuthProvider.tsx
  59:7  error  Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\AuthProvider.tsx:59:7
  57 |     const urlToken = searchParams.get("token");
  58 |     if (urlToken) {
> 59 |       setToken(urlToken);
     |       ^^^^^^^^ Avoid calling setState() directly within an effect
  60 |       saveToken(urlToken);
  61 |
  62 |       // Clean up URL without triggering navigation  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\components\ShellProvider.tsx
  27:7  error  Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\ShellProvider.tsx:27:7
  25 |   useEffect(() => {
  26 |     try {
> 27 |       setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
     |       ^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  28 |     } catch {
  29 |       /* SSR / privacy mode */
  30 |     }  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\components\WebSocketProvider.tsx
   8:33  error  Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     @typescript-eslint/no-explicit-any
  21:5   error  Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\WebSocketProvider.tsx:21:5
  19 |   useEffect(() => {
  20 |     wsClient.connect();
> 21 |     setIsConnected(true);
     |     ^^^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  22 |
  23 |     return () => {
  24 |       // Don't disconnect on unmount â€” Sidebar may still use wsClient  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\components\dashboard\TrackedWalletsTab.tsx
   4:8   warning  'Link' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           @typescript-eslint/no-unused-vars
  43:56  error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   @typescript-eslint/no-explicit-any
  49:67  error    Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   @typescript-eslint/no-explicit-any
  75:5   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\dashboard\TrackedWalletsTab.tsx:75:5
  73 |
  74 |   useEffect(() => {
> 75 |     setLoading(true);
     |     ^^^^^^^^^^ Avoid calling setState() directly within an effect
  76 |     Promise.all([fetchTracked(), fetchGroups()]).finally(() => setLoading(false));
  77 |   }, []);
  78 |  react-hooks/set-state-in-effect
  83:14  warning  'err' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            @typescript-eslint/no-unused-vars
  94:14  warning  'err' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\components\dashboard\WalletAlertsCard.tsx
   4:8   warning  'Link' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        @typescript-eslint/no-unused-vars
   5:21  warning  'ArrowUpRight' is defined but never used                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                @typescript-eslint/no-unused-vars
  29:7   error    Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\dashboard\WalletAlertsCard.tsx:29:7
  27 |   useEffect(() => {
  28 |     if (!token) {
> 29 |       setLoading(false);
     |       ^^^^^^^^^^ Avoid calling setState() directly within an effect
  30 |       return;
  31 |     }
  32 |  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\components\research\ChatRail.tsx
  36:3  warning  'chatId' is defined but never used  @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\components\wallet\LineageFlowGraph.tsx
   58:21  error    Unexpected any. Specify a different type                                                                                                                                                                @typescript-eslint/no-explicit-any
   59:22  error    Unexpected any. Specify a different type                                                                                                                                                                @typescript-eslint/no-explicit-any
   64:22  error    Unexpected any. Specify a different type                                                                                                                                                                @typescript-eslint/no-explicit-any
   65:22  error    Unexpected any. Specify a different type                                                                                                                                                                @typescript-eslint/no-explicit-any
   81:10  warning  'hoveredNode' is assigned a value but never used                                                                                                                                                        @typescript-eslint/no-unused-vars
   83:9   warning  The 'incomingP2P' logical expression could make the dependencies of useMemo Hook (at line 103) change on every render. To fix this, wrap the initialization of 'incomingP2P' in its own useMemo() Hook  react-hooks/exhaustive-deps
   84:9   warning  The 'outgoingP2P' logical expression could make the dependencies of useMemo Hook (at line 119) change on every render. To fix this, wrap the initialization of 'outgoingP2P' in its own useMemo() Hook  react-hooks/exhaustive-deps
   85:9   warning  The 'inflowsUSD' logical expression could make the dependencies of useMemo Hook (at line 131) change on every render. To fix this, wrap the initialization of 'inflowsUSD' in its own useMemo() Hook    react-hooks/exhaustive-deps
   86:9   warning  The 'outflowsUSD' logical expression could make the dependencies of useMemo Hook (at line 143) change on every render. To fix this, wrap the initialization of 'outflowsUSD' in its own useMemo() Hook  react-hooks/exhaustive-deps
  247:9   warning  'clusterAddresses' is assigned a value but never used                                                                                                                                                   @typescript-eslint/no-unused-vars
  267:9   warning  'handleRowEnter' is assigned a value but never used                                                                                                                                                     @typescript-eslint/no-unused-vars
  271:9   warning  'handleRowLeave' is assigned a value but never used                                                                                                                                                     @typescript-eslint/no-unused-vars
  276:28  warning  'side' is defined but never used                                                                                                                                                                        @typescript-eslint/no-unused-vars
  551:39  error    Unexpected any. Specify a different type                                                                                                                                                                @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\components\wallet\WalletSideRail.tsx
  5:26  warning  'formatPercent' is defined but never used  @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\components\wallets\Pagination.tsx
  24:5  error  Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\components\wallets\Pagination.tsx:24:5
  22 |
  23 |   useEffect(() => {
> 24 |     setPageInput(page.toString());
     |     ^^^^^^^^^^^^ Avoid calling setState() directly within an effect
  25 |   }, [page]);
  26 |
  27 |   const commitInput = () => {  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\hooks\useFavoriteToggle.ts
  28:6   warning  React Hook useEffect has a missing dependency: 'addresses'. Either include it or remove the dependency array                              react-hooks/exhaustive-deps
  28:14  warning  React Hook useEffect has a complex expression in the dependency array. Extract it to a separate variable so it can be statically checked  react-hooks/exhaustive-deps
  64:16  warning  'err' is defined but never used                                                                                                           @typescript-eslint/no-unused-vars

D:\project\poly\frontend\src\hooks\usePanelLayout.ts
  62:5  error  Error: Cannot access refs during render

React refs are values that are not needed for rendering. Refs should only be accessed outside of render, such as in event handlers or effects. Accessing a ref value (the `current` property) during render can cause your component not to update as expected (https://react.dev/reference/react/useRef).

D:\project\poly\frontend\src\hooks\usePanelLayout.ts:62:5
  60 |     setLocalRects({});
  61 |     setLocalZIndices({});
> 62 |     highestZRef.current = 10;
     |     ^^^^^^^^^^^^^^^^^^^ Cannot update ref during render
  63 |     setLastFailedMutation(null);
  64 |   }
  65 |  react-hooks/refs

D:\project\poly\frontend\src\hooks\useTradeNotifications.ts
  23:52  error  Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any

D:\project\poly\frontend\src\hooks\useWalletList.ts
  20:5  error  Error: Calling setState synchronously within an effect can trigger cascading renders

Effects are intended to synchronize state between React and external systems such as manually updating the DOM, state management libraries, or other platform APIs. In general, the body of an effect should do one or both of the following:
* Update external systems with the latest state from React.
* Subscribe for updates from some external system, calling setState in a callback function when external state changes.

Calling setState synchronously within an effect body causes cascading renders that can hurt performance, and is not recommended. (https://react.dev/learn/you-might-not-need-an-effect).

D:\project\poly\frontend\src\hooks\useWalletList.ts:20:5
  18 |     const id = ++requestId.current;
  19 |     let cancelled = false;
> 20 |     setLoading(true);
     |     ^^^^^^^^^^ Avoid calling setState() directly within an effect
  21 |     setError(null);
  22 |
  23 |     // Debounce search keystrokes; fire immediately otherwise  react-hooks/set-state-in-effect

D:\project\poly\frontend\src\hooks\useWebSocket.ts
   6:50  error  Unexpected any. Specify a different type                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             @typescript-eslint/no-explicit-any
  42:11  error  Error: Cannot access variable before it is declared

`connect` is accessed before it is declared, which prevents the earlier access from updating when this value changes over time.

D:\project\poly\frontend\src\hooks\useWebSocket.ts:42:11
  40 |         reconnectTimeout.current = setTimeout(() => {
  41 |           reconnectAttempts.current += 1;
> 42 |           connect();
     |           ^^^^^^^ `connect` accessed before it is declared
  43 |         }, timeout);
  44 |       } else {
  45 |         console.warn("WebSocket: max reconnect attempts reached, giving up.");

D:\project\poly\frontend\src\hooks\useWebSocket.ts:12:3
  10 |   const maxReconnectAttempts = 3;
  11 |
> 12 |   const connect = useCallback(() => {
     |   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> 13 |     const token = getAuthToken();
     | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> 14 |     if (!token) return;
     â€¦
     | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> 47 |     };
     | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
> 48 |   }, []);
     | ^^^^^^^^^^ `connect` is declared here
  49 |
  50 |   useEffect(() => {
  51 |     connect();  react-hooks/immutability

D:\project\poly\frontend\src\utils\api.ts
   53:14  warning  'e' is defined but never used             @typescript-eslint/no-unused-vars
  314:50  error    Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any
  315:43  error    Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any

âœ– 106 problems (65 errors, 41 warnings)
  2 errors and 0 warnings potentially fixable with the `--fix` option.


```

Result: FAIL. The full repository lint output contains many unrelated existing errors, but it also reports verification findings in focused/changed files: `frontend/src/components/ShellProvider.tsx:27` (`react-hooks/set-state-in-effect`), `frontend/src/hooks/usePanelLayout.ts:62` (`react-hooks/refs`), and a warning in `frontend/src/components/research/ChatRail.tsx:36` (`no-unused-vars`). These were not fixed because this task permits focused source changes only when verification proves a real contract mismatch; the findings are lint-rule issues, not demonstrated workspace-canvas contract failures. The output also contains numerous unrelated errors elsewhere in the repository, including `any`, hook, and unused-variable findings. No lint fix was made.

### `npx tsc --noEmit`

```text
src/components/research/__tests__/ChatTabs.test.tsx(7,78): error TS2741: Property 'workspace_id' is missing in type '{ chat_id: string; title: string; is_archived: boolean; created_at: string; updated_at: string; }' but required in type 'ResearchChat'.
src/hooks/useResearchHub.test.tsx(9,23): error TS2503: Cannot find namespace 'vi'.
src/hooks/useResearchHub.test.tsx(33,49): error TS7006: Parameter 'id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(34,48): error TS7006: Parameter 'chatId' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(52,54): error TS7006: Parameter '_id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(52,59): error TS7006: Parameter '_prompt' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(52,68): error TS7006: Parameter 'onEvent' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(66,54): error TS7006: Parameter 'id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(67,56): error TS7006: Parameter 'id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(83,58): error TS7006: Parameter '_id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(83,63): error TS7006: Parameter '_prompt' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(83,72): error TS7006: Parameter 'onEvent' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(117,60): error TS7006: Parameter '_id' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(117,65): error TS7006: Parameter '_prompt' implicitly has an 'any' type.
src/hooks/useResearchHub.test.tsx(117,74): error TS7006: Parameter 'onEvent' implicitly has an 'any' type.

```

Result: FAIL and remains an unresolved verification limitation. Standalone TypeScript checking reports focused test-file errors: the `ChatTabs.test.tsx` fixture is missing required `workspace_id`, and `useResearchHub.test.tsx` has a missing `vi` namespace plus implicit-any callback parameters. Vitest passes, but passing runtime tests do not establish a clean standalone type check. These errors were not treated as entirely pre-existing: they are explicitly recorded as unresolved focused-test verification issues. No source/test fix was made because the errors do not by themselves prove a runtime workspace-canvas contract mismatch, and the brief limits changes to fixes required by the matrix.

### `npm run build`

```text

> frontend@0.1.0 build
> next build

â–² Next.js 16.2.9 (Turbopack)
- Environments: .env.local

  Creating an optimized production build ...
âœ“ Compiled successfully in 3.9s
  Running TypeScript ...
  Finished TypeScript in 12.7s ...
  Collecting page data using 15 workers ...
  Generating static pages using 15 workers (0/14) ...
(node:9296) ExperimentalWarning: localStorage is not available because --localstorage-file was not provided.
(Use `node --trace-warnings ...` to show where the warning was created)
  Generating static pages using 15 workers (3/14) 
  Generating static pages using 15 workers (6/14) 
  Generating static pages using 15 workers (10/14) 
âœ“ Generating static pages using 15 workers (14/14) in 478ms
  Finalizing page optimization ...

Route (app)
â”Œ â—‹ /
â”œ â—‹ /_not-found
â”œ â—‹ /agents
â”œ â—‹ /dashboard
â”œ â—‹ /feed
â”œ â—‹ /hub
â”œ â—‹ /tools/wallet-tracker
â”œ â—‹ /tracker
â”œ Æ’ /wallet/[address]
â”œ â—‹ /wallets
â”œ â—‹ /wallets/curated
â”œ â—‹ /wallets/custom
â”” â—‹ /wallets/global


â—‹  (Static)   prerendered as static content
Æ’  (Dynamic)  server-rendered on demand


```

Result: PASS. Next.js 16.2.9 production build completed. Node emitted the existing localStorage experimental warning during static generation; no build failure occurred.

## Acceptance pass

Manual browser access was unavailable in this environment, so desktop/tablet/narrow responsive acceptance could not be performed interactively. Existing backend integration tests and frontend component tests provide automated coverage of selected workspace, panel, keyboard, and mock-boundary behaviors, but they do not replace or establish the unavailable desktop/tablet/narrow manual acceptance.

## Concerns

- Focused lint findings and unrelated repository-wide lint failures are distinguished above; none was broadly suppressed or unrelatedly fixed.
- Standalone TypeScript errors in focused test files remain unresolved verification limitations, despite the Vitest runtime suite passing.
- The harness did not independently exercise an empty database migration or rerun/idempotency scenario; this limitation is recorded above.
- No focused contract mismatch was found.
