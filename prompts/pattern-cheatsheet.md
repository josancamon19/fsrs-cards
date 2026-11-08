<!-- The LeetCode pattern cheat sheet: one line per pattern, "when you see X → think Y". Shown in the app (Patterns page)
and given to the pattern grader as the canonical pattern names. Keep the names in **bold** stable: cards use them. -->

# Pattern recognition cheat sheet

| Pattern | When you see… | …think |
|---|---|---|
| **Hash map / set** | "have I seen this before?", complements (`target - x`), counting, grouping by a key | trade O(n) memory for O(1) lookup; one pass, store what you need for later |
| **Two pointers** | sorted array, pairs/triplets summing to a target, palindromes, in-place partition | `i` from the left, `j` from the right, move the one that fixes the inequality; or expand both outward from a center |
| **Fast & slow pointers** | linked list cycle, middle node, "duplicate in 1..n without extra space" | slow moves 1, fast moves 2; they meet inside a cycle; restart one at head to find the entry |
| **Sliding window** | longest/shortest **contiguous** subarray/substring with a constraint | grow `right`, shrink `left` while invalid, keep a counter of the window; answer updates each step |
| **Prefix sum** | subarray sums, "sum equals k", range queries, balance of 0s/1s | `sum(i..j) = P[j+1] - P[i]`; with a hash map of seen prefixes → count subarrays in O(n) |
| **Binary search** | sorted / rotated input, or "minimum X such that feasible(X)" (monotone answer) | halve the search space; for "search on answer" binary-search the value and test feasibility |
| **Stack / monotonic stack** | matching brackets, nested decoding, "next greater/smaller element", histogram areas | push until the invariant breaks, pop and resolve; a monotonic stack gives each element its nearest bigger/smaller |
| **Heap / top-k** | k largest/smallest/closest/most frequent, merge k sorted, running median | keep a size-k heap (min-heap for top-k largest); two heaps for the median |
| **Intervals** | ranges, meetings, overlaps, merging, "minimum rooms" | sort by start (or end), sweep and compare to the last kept interval; count overlaps with a min-heap of ends |
| **Linked list** | reverse, merge, reorder, remove nth, deep copy | dummy head + `prev/cur/next` rewiring; draw the pointers before coding |
| **Tree DFS** | anything about paths, heights, subtrees, BST validity, LCA | recurse: what do I need from my children, what do I return to my parent? (global answer ≠ return value) |
| **Tree BFS** | level by level, right-side view, min depth, zigzag | queue; process `len(queue)` nodes per level |
| **Graph BFS/DFS** | grid of cells, islands, connected regions, fewest steps on an unweighted graph | visited set + neighbors; BFS for shortest steps, DFS/flood fill for regions; multi-source BFS for "spreading" |
| **Topological sort** | prerequisites, dependencies, ordering with constraints, cycle in a directed graph | indegree counts + queue of zero-indegree nodes (Kahn); fewer than n popped ⇒ cycle |
| **Union-Find** | dynamic connectivity, merging groups, "redundant edge", number of components | `find` with path compression + `union` by rank; an edge whose ends already share a root closes a cycle |
| **Shortest path** | weighted edges, cheapest/fastest route, "within k stops" | Dijkstra (min-heap on distance) for non-negative weights; Bellman-Ford / BFS-by-layers when stops are limited |
| **Backtracking** | "all" subsets/permutations/combinations, place pieces, search a word on a board | choose → recurse → un-choose; prune early; the recursion tree *is* the search space |
| **Dynamic programming** | "number of ways", min/max cost, can-you-reach, overlapping subproblems over prefixes/indices/two strings | define `dp[state]` in words, write the transition from smaller states, base case, then the order to fill |
| **Greedy** | a local best choice is provably safe: max subarray, jump reachability, gas station, partition labels | keep one running best/reach; prove "taking it now never hurts" |
| **Trie** | prefix queries, many words against one board/text, wildcard word search | tree of characters with an end flag; walk it in step with the input |
| **Bit manipulation** | "appears once while others twice", counting bits, missing number, subsets as masks | XOR cancels pairs; `n & (n-1)` drops the lowest set bit |
| **Matrix simulation** | rotate, spiral, set zeroes: the work is index bookkeeping | transpose + reverse rows; shrink four boundaries layer by layer |
| **Design** | build a class with O(1)/O(log n) operations (LRU cache, time map, random set) | combine structures: hash map for lookup + linked list/array/heap for order |

**Recursion vs. iteration:** reach for recursion when the problem is self-similar (trees, nested structures, "all ways"),
and when the answer for a big input is built from answers to strictly smaller inputs. Memoize it the moment the same
sub-call repeats: that is DP.
