"use client";

import { useEffect, useState } from "react";
import { getSmartMoneyAlerts, toggleWatchlist } from "@/utils/api";
import { formatCurrency } from "@/utils/format";
import Link from "next/link";
import { Zap, ExternalLink, Copy, Check, PlusCircle } from "lucide-react";

type FeedItem = {
  id: string;
  type: "call" | "trade" | "deposit";
  timestamp: string;
  data: any;
};

export default function AlphaFeedPage() {
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [subcategoryFilter, setSubcategoryFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(100);
  const [totalCount, setTotalCount] = useState(0);
  const [activeTab, setActiveTab] = useState<"deposits" | "trades">("deposits");
  const [watchlistStatus, setWatchlistStatus] = useState<Record<string, 'idle' | 'loading' | 'success'>>({});
  const [searchQuery, setSearchQuery] = useState("");

  const handleAddToWatchlist = async (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    try {
      setWatchlistStatus(prev => ({ ...prev, [address]: 'loading' }));
      await toggleWatchlist(address, 'add');
      setWatchlistStatus(prev => ({ ...prev, [address]: 'success' }));
      setTimeout(() => {
        setWatchlistStatus(prev => ({ ...prev, [address]: 'idle' }));
      }, 3000);
    } catch (error) {
      console.error("Failed to add to watchlist", error);
      setWatchlistStatus(prev => ({ ...prev, [address]: 'idle' }));
      alert("Failed to add to watchlist. Please make sure you are logged in.");
    }
  };

  const getTier = (amount: number): string => {
    if (amount >= 100000) return "Tier 4";
    if (amount >= 50000) return "Tier 3";
    if (amount >= 20000) return "Tier 2";
    if (amount >= 5000) return "Tier 1";
    return "Unranked";
  };

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      try {
        const alertType = activeTab === "deposits" ? "LARGE_DEPOSIT" : "LARGE_TRADE";
        const [smartMoneyRes] = await Promise.all([
          getSmartMoneyAlerts(limit, (page - 1) * limit, alertType, tierFilter, categoryFilter, subcategoryFilter)
        ]);

        const items: FeedItem[] = [];
        setTotalCount(smartMoneyRes?.total_count || 0);

        // Add smart money alerts (unified trades + deposits)
        const alerts = smartMoneyRes?.alerts || [];
        alerts.forEach((a: any) => {
          if (a.alert_type === "LARGE_TRADE") {
            items.push({ id: `trade-${a.transaction_hash}`, type: "trade", timestamp: a.created_at, data: a });
          } else if (a.alert_type === "LARGE_DEPOSIT") {
            items.push({ id: `dep-${a.transaction_hash}`, type: "deposit", timestamp: a.created_at, data: a });
          }
        });

        // Sort by timestamp descending
        items.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
        setFeed(items);
      } catch (e) {
        console.error("Failed to fetch alpha feed", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [page, limit, activeTab, tierFilter, categoryFilter, subcategoryFilter]);

  const formatAddress = (addr: string) => {
    if (!addr) return "Unknown";
    return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
  };

  const handleCopy = (e: React.MouseEvent, address: string) => {
    e.preventDefault();
    navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / limit));

  const renderPaginationControls = () => {
    return (
      <div className="flex items-center space-x-1">
        <button onClick={() => setPage(1)} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">First</button>
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&lt;</button>
        <span className="text-xs text-muted-fg mx-1">Page {page} of {totalPages}</span>
        <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">&gt;</button>
        <button onClick={() => setPage(totalPages)} disabled={page >= totalPages} className="px-2 py-0.5 bg-surface-2 hover:bg-surface-3 transition-colors rounded text-xs text-foreground disabled:opacity-50">Last</button>
        
        <div className="flex items-center space-x-1 ml-4 border-l border-border pl-4">
          <span className="text-xs text-muted-fg">Jump to:</span>
          <input
            type="number"
            min={1}
            max={totalPages}
            defaultValue={page}
            key={`jump-${page}`}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const val = Number(e.currentTarget.value);
                if (val >= 1 && val <= totalPages) setPage(val);
              }
            }}
            onBlur={(e) => {
              const val = Number(e.currentTarget.value);
              if (val >= 1 && val <= totalPages) setPage(val);
              else e.currentTarget.value = String(page);
            }}
            className="w-12 bg-surface-2 border border-border rounded px-1.5 py-0.5 text-xs outline-none focus:border-primary text-foreground text-center"
          />
        </div>
      </div>
    );
  };

  return (
    <div className="w-full h-full flex flex-col bg-background">
      {/* Toolbar */}
      <div className="flex items-center gap-2 mb-4 flex-shrink-0 w-full">
        <Zap className="text-primary w-5 h-5" />
        <h1 className="text-xl font-bold tracking-tight text-foreground">
          Activity
        </h1>
        
        <div className="flex bg-surface-2 p-1 rounded-lg ml-6">
          <button
            onClick={() => { setActiveTab("deposits"); setPage(1); setTierFilter("all"); setCategoryFilter("all"); setSubcategoryFilter("all"); }}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "deposits"
                ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            Deposits
          </button>
          <button
            onClick={() => { setActiveTab("trades"); setPage(1); setTierFilter("all"); setCategoryFilter("all"); setSubcategoryFilter("all"); }}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-all ${
              activeTab === "trades"
                ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-fg hover:text-foreground"
            }`}
          >
            Trades
          </button>
        </div>
        
        <div className="ml-auto flex items-center gap-2">
          {/* Wallet Search */}
          <input
            type="text"
            placeholder="Search wallet..."
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
            className="bg-surface-2 border border-border rounded px-3 py-1.5 text-xs outline-none focus:border-primary text-foreground placeholder-muted-fg w-36 font-mono"
          />
          <span className="text-xs font-semibold text-muted-fg uppercase ml-2">Show</span>
          <select 
            className="bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none focus:border-primary text-foreground"
            value={limit}
            onChange={(e) => {
              setLimit(Number(e.target.value));
              setPage(1);
            }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
          
          {activeTab === "trades" && (
            <>
              <span className="text-xs font-semibold text-muted-fg uppercase ml-2">Filter Tier</span>
              <select 
                className="bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none focus:border-primary text-foreground"
                value={tierFilter}
                onChange={(e) => {
                  setTierFilter(e.target.value);
                  setPage(1);
                }}
              >
                <option value="all">All</option>
                <option value="Tier 4">Tier 4 (100k+)</option>
                <option value="Tier 3">Tier 3 (50k+)</option>
                <option value="Tier 2">Tier 2 (20k+)</option>
                <option value="Tier 1">Tier 1 (5k+)</option>
              </select>
            </>
          )}
          
          {activeTab === "trades" && (
            <>
              <span className="text-xs font-semibold text-muted-fg uppercase ml-2">Category</span>
              <select 
                className="bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none focus:border-primary text-foreground"
                value={categoryFilter}
                onChange={(e) => {
                  setCategoryFilter(e.target.value);
                  setSubcategoryFilter("all");
                  setPage(1);
                }}
              >
                <option value="all">All</option>
                <option value="Politics">Politics</option>
                <option value="Sports">Sports</option>
                <option value="Esports">Esports</option>
                <option value="Crypto">Crypto</option>
                <option value="Finance">Finance</option>
                <option value="Culture">Culture</option>
                <option value="Mentions">Mentions</option>
                <option value="Weather">Weather</option>
                <option value="Economics">Economics</option>
                <option value="Tech">Tech</option>
              </select>

              <span className="text-xs font-semibold text-muted-fg uppercase ml-2">Subcategory</span>
              <select 
                className="bg-surface-2 border border-border rounded px-2 py-1 text-xs outline-none focus:border-primary text-foreground"
                value={subcategoryFilter}
                onChange={(e) => {
                  setSubcategoryFilter(e.target.value);
                  setPage(1);
                }}
              >
                <option value="all">All</option>
              </select>
            </>
          )}
          
          <div className="ml-2 border-l border-border pl-2">
            {renderPaginationControls()}
          </div>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-lg overflow-hidden shadow-sm flex-1 min-h-0 flex flex-col">
        <div className="overflow-x-auto overflow-y-auto flex-1 relative">
          <table className="w-full text-left text-sm whitespace-nowrap border-collapse">
              <thead>
                <tr className="border-b border-border bg-surface-2/40 text-xs text-muted-fg font-mono uppercase tracking-wider">
                  <th className="py-3 px-4 font-medium w-12">No.</th>
                  <th className="py-3 px-4 font-medium w-24">Time</th>
                  {activeTab === "deposits" && (
                    <th className="py-3 px-4 font-medium w-32">Tier</th>
                  )}
                  {activeTab === "trades" && (
                    <th className="py-3 px-4 font-medium w-28">Category</th>
                  )}
                  {activeTab === "trades" && (
                    <th className="py-3 px-4 font-medium w-28">Subcategory</th>
                  )}
                  <th className="py-3 px-4 font-medium w-32">Size (USDC)</th>
                  <th className="py-3 px-4 font-medium w-32">Balance</th>
                  <th className="py-3 px-4 font-medium w-32">Open Position</th>
                  <th className="py-3 px-4 font-medium">Wallet & Links</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {loading ? (
                  <tr>
                    <td colSpan={activeTab === "trades" ? 8 : 7} className="py-12 text-center">
                      <div className="inline-block animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                    </td>
                  </tr>
                ) : feed.length === 0 ? (
                  <tr>
                    <td colSpan={activeTab === "trades" ? 8 : 7} className="py-12 text-center text-muted-fg font-mono text-sm">
                      No activity found in the feed.
                    </td>
                  </tr>
                ) : (
                  feed
                    .filter((item) => activeTab === "deposits" ? item.type === "deposit" : item.type === "trade").length === 0 ? (
                    <tr>
                      <td colSpan={activeTab === "trades" ? 8 : 7} className="py-12 text-center text-muted-fg font-mono text-sm">
                        No activity matches the selected filters.
                      </td>
                    </tr>
                  ) : (
                  feed
                    .filter((item) => activeTab === "deposits" ? item.type === "deposit" : item.type === "trade")
                    .filter((item) => !searchQuery || (item.data.address || "").toLowerCase().includes(searchQuery.toLowerCase()))
                    .map((item, index) => {
                    const dateObj = new Date(item.timestamp);
                    const time = dateObj.toLocaleString([], { 
                      year: 'numeric', month: 'short', day: 'numeric', 
                      hour: '2-digit', minute: '2-digit' 
                    });
                    
                    const tier = getTier(item.data.amount_usdc);
                    const tierColors: Record<string, string> = {
                      "Tier 5": "text-purple-500 bg-purple-500/10 border-purple-500/20",
                      "Tier 4": "text-red-500 bg-red-500/10 border-red-500/20",
                      "Tier 3": "text-orange-500 bg-orange-500/10 border-orange-500/20",
                      "Tier 2": "text-yellow-500 bg-yellow-500/10 border-yellow-500/20",
                      "Tier 1": "text-green-500 bg-green-500/10 border-green-500/20",
                      "Unranked": "text-muted-fg bg-surface-2 border-border"
                    };

                    const categoryColors: Record<string, string> = {
                      "Crypto": "text-blue-500 bg-blue-500/10 border-blue-500/20",
                      "Politics": "text-purple-500 bg-purple-500/10 border-purple-500/20",
                      "Sports": "text-emerald-500 bg-emerald-500/10 border-emerald-500/20",
                      "Pop Culture": "text-pink-500 bg-pink-500/10 border-pink-500/20",
                      "Business": "text-amber-500 bg-amber-500/10 border-amber-500/20",
                    };

                    const getCategoryColor = (cat: string) => categoryColors[cat] || "text-muted-fg bg-surface-2 border-border";

                    const rowNum = (page - 1) * limit + index + 1;

                    return (
                      <tr key={`${item.id}-${index}`} className="hover:bg-surface-2/20 transition-colors group cursor-default">
                        <td className="py-2.5 px-4 text-xs font-mono text-muted-fg">{rowNum}</td>
                        <td className="py-2.5 px-4 text-xs font-mono text-subtle">{time}</td>
                        {activeTab === "deposits" && (
                          <td className="py-2.5 px-4">
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide border ${tierColors[tier] || tierColors["Unranked"]}`}>
                              {tier.toUpperCase()}
                            </span>
                          </td>
                        )}
                        {activeTab === "trades" && (
                          <td className="py-2.5 px-4">
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide border ${getCategoryColor(item.data.category || 'N/A')}`}>
                              {item.data.category || "N/A"}
                            </span>
                          </td>
                        )}
                        {activeTab === "trades" && (
                          <td className="py-2.5 px-4">
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide border ${getCategoryColor(item.data.subcategory || 'N/A')}`}>
                              {item.data.subcategory || "N/A"}
                            </span>
                          </td>
                        )}
                        <td className="py-2.5 px-4 font-mono font-bold text-foreground">
                          {formatCurrency(item.data.amount_usdc)}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-muted-fg">
                          {item.data.wallet_stats?.balance ? formatCurrency(item.data.wallet_stats.balance) : "—"}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-muted-fg">
                          {item.data.wallet_stats?.position_value ? formatCurrency(item.data.wallet_stats.position_value) : "—"}
                        </td>
                        <td className="py-2.5 px-4 truncate max-w-md w-full">
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-muted-fg flex items-center gap-1.5">
                              by 
                              <div className="flex items-center gap-1">
                                <Link href={`/wallet/${item.data.address}`} className="text-primary hover:underline font-mono bg-primary/5 px-1.5 py-0.5 rounded border border-primary/10" title={item.data.address}>
                                  {formatAddress(item.data.address)}
                                </Link>
                                <button
                                  onClick={(e) => handleCopy(e, item.data.address)}
                                  className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors"
                                  title="Copy Address"
                                >
                                  {copiedAddress === item.data.address ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                                </button>
                              </div>
                            </span>
                            <div className="flex items-center gap-4">
                              <a href={`https://polygonscan.com/tx/${item.data.transaction_hash}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs font-medium text-primary/60 hover:text-primary transition-colors">
                                PolygonScan <ExternalLink size={12} />
                              </a>
                              <a href={`https://activity.polymarket-tools.com/?address=${item.data.address}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs font-medium text-[#00B4D8]/60 hover:text-[#00B4D8] transition-colors">
                                PolyTools <ExternalLink size={12} />
                              </a>
                              <a href={`https://polymarket.com/profile/${item.data.address}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs font-medium text-blue-400/60 hover:text-blue-400 transition-colors">
                                PolyMarket <ExternalLink size={12} />
                              </a>
                              <div className="w-px h-3 bg-border mx-1"></div>
                              <button
                                onClick={(e) => handleAddToWatchlist(e, item.data.address)}
                                disabled={watchlistStatus[item.data.address] === 'loading' || watchlistStatus[item.data.address] === 'success'}
                                className="flex items-center gap-1 text-xs font-medium text-muted-fg hover:text-foreground transition-colors disabled:opacity-50"
                                title="Add to Watchlist"
                              >
                                Track {watchlistStatus[item.data.address] === 'success' ? <Check size={12} className="text-green-500" /> : <PlusCircle size={12} />}
                              </button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                  )
                )}
              </tbody>
            </table>
          </div>
      </div>
      
      {/* Bottom Pagination Controls */}
      <div className="flex justify-center items-center py-4 px-2">
        {renderPaginationControls()}
      </div>
    </div>
  );
}
