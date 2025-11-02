"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import "./app.css";
import type {
  WikiEditData,
  BubbleState,
  HeadlineState,
  StatsState,
  TooltipState,
  ConnectionStatus,
  SentimentData, 
} from "@/types/types";

// configuration constants
const BUBBLE_LIFETIME = 10000;
const FADE_DURATION = 2000;
const MAX_BUBBLES = 50;
const LEADERBOARD_SIZE = 10;
const EVENTSTREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange";
const BUBBLE_DELAY = 1500;
const MAX_DEGREES_OF_SEPARATION = 4;


// utility functions
const sizeMap = {
  large: 240,
  medium: 180,
  small: 120,
  tiny: 90,
};

const edinburghCache = new Map<string, number>();

function getBubbleAttributes(
  data: WikiEditData,
  changeSize: number,
  sentimentCompound: number
) {
  const absSize = Math.abs(changeSize);
  let size: BubbleState["size"];
  let colorClass: string;

  if (absSize >= 2000) size = "large";
  else if (absSize >= 500) size = "medium";
  else if (absSize >= 100) size = "small";
  else size = "tiny";

  if (data.bot) {
    colorClass = "bot";
  } else if (data.user) {
    if (sentimentCompound > 0.05) {
      colorClass = "sentiment-positive";
    } else if (sentimentCompound < -0.05) {
      colorClass = "sentiment-negative";
    } else {
      colorClass = "sentiment-neutral";
    }
  } else {
    colorClass = "anon";
  }
  return { size, colorClass };
}

function checkOverlap(
  newPos: { x: number; y: number; radius: number },
  existingBubbles: BubbleState[]
) {
  for (const bubble of existingBubbles) {
    const existingRadius = sizeMap[bubble.size] / 2;
    const existingX = bubble.x + existingRadius;
    const existingY = bubble.y + existingRadius;
    const newX = newPos.x + newPos.radius;
    const newY = newPos.y + newPos.radius;
    const dx = newX - existingX;
    const dy = newY - existingY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const minDistance = newPos.radius + existingRadius + 10;
    if (distance < minDistance) return true;
  }
  return false;
}

function getRandomPosition(
  containerEl: HTMLDivElement | null,
  size: BubbleState["size"],
  existingBubbles: BubbleState[]
): { x: number; y: number } | null {
  if (!containerEl) return null;
  const rect = containerEl.getBoundingClientRect();
  const bubbleSize = sizeMap[size];
  const radius = bubbleSize / 2;
  const maxX = rect.width - bubbleSize - 40;
  const maxY = rect.height - bubbleSize - 40;
  if (maxX <= 0 || maxY <= 0) return null;
  let attempts = 0;
  const maxAttempts = 100;
  while (attempts < maxAttempts) {
    const pos = {
      x: Math.random() * maxX + 20,
      y: Math.random() * maxY + 20,
      radius: radius,
    };
    if (!checkOverlap(pos, existingBubbles)) return pos;
    attempts++;
  }
  return { x: Math.random() * maxX + 20, y: Math.random() * maxY + 20 };
}

function getTimeAgo(timestamp: Date, now: Date) {
  const seconds = Math.floor((now.getTime() - timestamp.getTime()) / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

function escapeHtml(text: string) {
  if (typeof text !== "string") return "";
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function decodeHtml(html: string): string {
  if (typeof document === "undefined") return html;
  const txt = document.createElement("textarea");
  txt.innerHTML = html;
  return txt.value;
}

function truncateForBubble(text: string, size: BubbleState["size"]): string {
  if (!text) return "";
  const maxLengths = { large: 140, medium: 90, small: 55, tiny: 30 };
  const maxLength = maxLengths[size];
  if (text.length <= maxLength) return text;
  const truncated = text.substring(0, maxLength);
  const lastSpace = truncated.lastIndexOf(" ");
  return (
    (lastSpace > maxLength * 0.7
      ? truncated.substring(0, lastSpace)
      : truncated) + "..."
  );
}

async function getDegreesFromEdinburgh(articleTitle: string): Promise<number> {
  const normalize = (t: string) => t.trim().toLowerCase();
  const startKey = normalize(articleTitle);
  const maxDepth = MAX_DEGREES_OF_SEPARATION;

  if (edinburghCache.has(startKey)) return edinburghCache.get(startKey)!;

  try {
    const queue: { title: string; depth: number }[] = [
      { title: articleTitle, depth: 0 },
    ];
    const visited = new Set<string>([startKey]);

    while (queue.length > 0) {
      const { title, depth } = queue.shift()!;
      const titleKey = normalize(title);
      if (depth >= maxDepth) continue;

      const resp = await fetch(
        `https://en.wikipedia.org/w/api.php?action=query&titles=${encodeURIComponent(
          title
        )}&prop=links&pllimit=500&format=json&origin=*`
      );
      const json = await resp.json();
      const pages = json.query?.pages;
      if (!pages) {
        edinburghCache.set(titleKey, 999);
        continue;
      }

      const page = Object.values(pages)[0] as any;
      const links: any[] = page.links || [];
      const linkTitles = links
        .map((l) => (l && l.title ? String(l.title) : ""))
        .filter((t) => t && !t.includes(":"));

      const foundDirect = linkTitles.some((lt) =>
        lt.toLowerCase().includes("edinburgh")
      );
      if (foundDirect) {
        const degrees = depth + 1;
        if (degrees <= maxDepth) {
          edinburghCache.set(startKey, degrees);
          for (const lt of linkTitles) {
            if (lt.toLowerCase().includes("edinburgh")) {
              edinburghCache.set(normalize(lt), 1);
            }
          }
          return degrees;
        } else {
          edinburghCache.set(startKey, 999);
          return 999;
        }
      }

      for (const lt of linkTitles) {
        const lk = normalize(lt);
        const cached = edinburghCache.get(lk);
        if (typeof cached === "number" && cached !== 999) {
          const totalDegrees = depth + 1 + cached;
          if (totalDegrees <= maxDepth) {
            edinburghCache.set(startKey, totalDegrees);
            return totalDegrees;
          }
        }
      }

      if (depth + 1 < maxDepth) {
        for (const lt of linkTitles) {
          const lk = normalize(lt);
          if (!visited.has(lk)) {
            visited.add(lk);
            queue.push({ title: lt, depth: depth + 1 });
          }
        }
      }
    }
    edinburghCache.set(startKey, 999);
    return 999;
  } catch (error) {
    console.error("Error checking Edinburgh connection:", error);
    return 999;
  }
}

/**
 * provides a 'Date' object that updates to force components using 'getTimeAgo' to re-render.
 */
function useTimeAgo(interval = 10000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), interval);
    return () => clearInterval(timer);
  }, [interval]);
  return now;
}


/**
 * manages the state and handlers for the tooltip.
 */
function useTooltip() {
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    content: "",
    x: 0,
    y: 0,
  });

  const showTooltip = useCallback(
    (content: string, e: React.MouseEvent) => {
      setTooltip({
        visible: true,
        content,
        x: e.pageX + 15,
        y: e.pageY + 15,
      });
    },
    []
  );

  const hideTooltip = useCallback(() => {
    setTooltip((prev) => ({ ...prev, visible: false }));
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (tooltip.visible) {
        setTooltip((prev) => ({ ...prev, x: e.pageX + 15, y: e.pageY + 15 }));
      }
    },
    [tooltip.visible]
  );

  return {
    tooltip,
    showTooltip,
    hideTooltip,
    mouseMoveProps: { onMouseMove: handleMouseMove },
  };
}


/**
 * manages EventSource connection, data processing queue,
 */
function useWikipediaEdits(
  edinburghMode: boolean,
  visContainerRef: React.RefObject<HTMLDivElement | null>
) {
  const [status, setStatus] = useState<{ type: ConnectionStatus; text: string }>(
    { type: "connecting", text: "Connecting to Wikipedia EventStreams..." }
  );
  
  const [stats, setStats] = useState<StatsState>({
    totalEdits: 0,
    queueCount: 0,
    lastEdit: "-",
    filteredByEdinburgh: 0,
    positiveCount: 0,
    neutralCount: 0,
    negativeCount: 0,
  });
  const [headlines, setHeadlines] = useState<HeadlineState[]>([]);
  const [bubbles, setBubbles] = useState<BubbleState[]>([]);

  const eventSourceRef = useRef<EventSource | null>(null);
  const bubbleQueueRef = useRef<WikiEditData[]>([]);
  const isProcessingQueueRef = useRef(false);

  const addBubble = useCallback(
    (data: WikiEditData, changeSize: number, headline: string, sentiment: SentimentData) => {

      setBubbles((prevBubbles) => {
        const { size, colorClass } = getBubbleAttributes(data, changeSize, sentiment.compound);
        
        const position = getRandomPosition(
          visContainerRef.current,
          size,
          prevBubbles
        );
        if (!position) return prevBubbles;

        const newBubble: BubbleState = {
          id: `bubble-${data.id}-${Math.random()}`,
          title: headline,
          user: data.user || "Anonymous",
          changeSize: changeSize,
          size: size,
          colorClass: colorClass, 
          x: position.x,
          y: position.y,
          state: "appearing",
          edinburghDegrees: data.edinburghDegrees,
          rawData: data,
          sentiment: sentiment,
        };

        setTimeout(() => {
          setBubbles((prev) =>
            prev.map((b) =>
              b.id === newBubble.id ? { ...b, state: "fading" } : b
            )
          );
        }, BUBBLE_LIFETIME);

        setTimeout(() => {
          setBubbles((prev) => prev.filter((b) => b.id !== newBubble.id));
        }, BUBBLE_LIFETIME + FADE_DURATION);

        const updatedBubbles = [...prevBubbles, newBubble];
        return updatedBubbles.length > MAX_BUBBLES
          ? updatedBubbles.slice(1)
          : updatedBubbles;
      });
    },
    [visContainerRef]
  );

  const addHeadline = useCallback(
    (data: WikiEditData, changeSize: number, headline: string, sentiment: SentimentData) => {
      const newHeadline: HeadlineState = {
        id: `headline-${data.id}-${Math.random()}`,
        title: headline,
        user: data.user || "Anonymous",
        changeSize: changeSize,
        timestamp: new Date(data.timestamp * 1000),
        wiki: data.wiki,
        comment: data.comment || "",
        sentiment: sentiment,
      };
      setHeadlines((prev) => [newHeadline, ...prev].slice(0, LEADERBOARD_SIZE));
    },
    []
  );

  const processEdit = useCallback(
    async (data: WikiEditData) => {
      const changeSize = (data.length?.new || 0) - (data.length?.old || 0);

      const degrees = await getDegreesFromEdinburgh(data.title);
      data.edinburghDegrees = degrees;

      if (edinburghMode) {
        if (degrees > MAX_DEGREES_OF_SEPARATION) {
          setStats((prev) => ({
            ...prev,
            filteredByEdinburgh: (prev.filteredByEdinburgh || 0) + 1,
          }));
          return;
        }
      }

      let headlineToUse = data.title;
      let sentiment: SentimentData = { neg: 0, neu: 1, pos: 0, compound: 0 };
      
      try {
        const response = await fetch("/api/generate-headline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: data.title,
            user: data.user,
            comment: data.comment,
          }),
        });

        if (response.ok) {
          const { headline, sentiment: apiSentiment } = await response.json();
          headlineToUse = decodeHtml(headline);
          sentiment = apiSentiment;
        } else {
          console.error("API Error, using fallback title");
        }
      } catch (error) {
        console.error("Failed to fetch headline, using fallback title:", error);
      }

      addBubble(data, changeSize, headlineToUse, sentiment);
      addHeadline(data, changeSize, headlineToUse, sentiment);

      setStats((prev) => {
        const newStats = {
          ...prev,
          totalEdits: prev.totalEdits + 1,
          lastEdit: new Date().toLocaleTimeString(),
        };

        if (sentiment.compound > 0.05) {
          newStats.positiveCount += 1;
        } else if (sentiment.compound < -0.05) {
          newStats.negativeCount += 1;
        } else {
          newStats.neutralCount += 1;
        }
        
        return newStats;
      });
    },
    [addBubble, addHeadline, edinburghMode]
  );

  const processQueue = useCallback(() => {
    if (isProcessingQueueRef.current || bubbleQueueRef.current.length === 0) {
      return;
    }
    isProcessingQueueRef.current = true;

    const data = bubbleQueueRef.current.shift();
    setStats((prev) => ({
      ...prev,
      queueCount: bubbleQueueRef.current.length,
    }));

    if (data) {
      processEdit(data);
    }

    setTimeout(() => {
      isProcessingQueueRef.current = false;
      processQueue();
    }, BUBBLE_DELAY);
  }, [processEdit]);

  useEffect(() => {
    try {
      const eventSource = new EventSource(EVENTSTREAM_URL);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setStatus({
          type: "connected",
          text: "Connected to Wikipedia EventStreams",
        });
      };
      eventSource.onerror = () => {
        setStatus({
          type: "disconnected",
          text: "Connection error - Reconnecting...",
        });
      };
      eventSource.onmessage = (event) => {
        try {
          const data: WikiEditData = JSON.parse(event.data);
          if (
            data.wiki === "enwiki" &&
            data.namespace === 0 &&
            data.type === "edit" &&
            data.title &&
            !data.bot &&
            data.comment &&
            data.comment.trim().length > 0 &&
            data.title.length > 3 &&
            Math.abs((data.length?.new || 0) - (data.length?.old || 0)) > 20
          ) {
            bubbleQueueRef.current.push(data);
            setStats((prev) => ({
              ...prev,
              queueCount: bubbleQueueRef.current.length,
            }));
            processQueue();
          }
        } catch (error) {
          console.error("Error parsing event:", error);
        }
      };
    } catch (error) {
      console.error("Failed to connect:", error);
      setStatus({ type: "disconnected", text: "Failed to connect" });
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [processQueue]);

  return { status, stats, headlines, bubbles };
}

// tooltip component
const Tooltip = React.memo(
  ({ visible, x, y, content }: TooltipState) => {
    if (!visible) return null;
    return (
      <div
        className="tooltip"
        style={{ display: "block", left: x, top: y }}
        dangerouslySetInnerHTML={{ __html: content }}
      />
    );
  }
);
Tooltip.displayName = "Tooltip";


// header component
interface HeaderProps {
  status: { type: ConnectionStatus; text: string };
  edinburghMode: boolean;
  onEdinburghModeChange: (checked: boolean) => void;
}

const Header = React.memo(
  ({ status, edinburghMode, onEdinburghModeChange }: HeaderProps) => {
    return (
      <div className="main-header-banner-wrapper">
        <div className="main-header-banner">
          <div>
            <h1>
              <span className="h1-large-letter">W</span>IKI
              <span className="h1-large-letter">W</span><span className="kerning-fix">ATCH</span>
            </h1>
            <p className="subtitle">
              the real-time climate of wikipedia
            </p>
          </div>
          <div className="status-bar">
            <div
              className={`status-indicator ${status.type}`}
              id="status-indicator"
            ></div>
            <span id="status-text">{status.text}</span>
            <label
              style={{
                marginLeft: "auto",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                cursor: "pointer",
                userSelect: "none",
                fontWeight: "500",
              }}
            >
              <input
                type="checkbox"
                checked={edinburghMode}
                onChange={(e) => onEdinburghModeChange(e.target.checked)}
              />
              <img
                src="/Flag_of_Scotland.svg.png"
                alt="Scotland flag"
                style={{
                  width: '1.2em',
                  height: '1em',
                  verticalAlign: 'middle'
                }}
              />
              <span>Edinburgh Mode</span>
            </label>
          </div>
        </div>
      </div>
    );
  }
);
Header.displayName = "Header";

// leaderboard component
const LeaderboardItem = React.memo(
  ({ headline, rank, now }: {
    headline: HeadlineState;
    rank: number;
    now: Date;
  }) => {
    const timeAgo = getTimeAgo(headline.timestamp, now);
    const changeText =
      headline.changeSize > 0 ? `+${headline.changeSize}` : headline.changeSize;
    
    const sentiment = headline.sentiment;
    let sentimentColor = "#d4a853"; // default
    if (sentiment) {
      if (sentiment.compound > 0.05) {
        sentimentColor = "#5a7eb8"; // positive
      } else if (sentiment.compound < -0.05) {
        sentimentColor = "#c94343"; // negative
      }
    }

    return (
      <div
        className="leaderboard-item"
        data-headline-id={headline.id}
        data-rank={rank + 1}
      >
        <div className="leaderboard-rank">#{rank + 1}</div>
        <div className="leaderboard-headline">{headline.title}</div>
        <div className="leaderboard-meta">
          <span
            className="leaderboard-badge edits"
            style={{
              backgroundColor: `${sentimentColor}20`,
              color: sentimentColor,
            }}
          >
            {changeText} bytes
          </span>
          <span className="leaderboard-badge time">🕐 {timeAgo}</span>
        </div>
      </div>
    );
  }
);
LeaderboardItem.displayName = "LeaderboardItem";

const Leaderboard = React.memo(
  ({ headlines, now }: { headlines: HeadlineState[]; now: Date }) => {
    return (
      <div className="leaderboard" id="leaderboard">
        <h2>📈 Live Headlines</h2>
        <div id="leaderboard-items">
          {headlines.length === 0 && (
            <div
              style={{
                padding: "20px",
                textAlign: "center",
                color: "#666",
                fontSize: "14px",
              }}
            >
              Connecting to Wikipedia...
            </div>
          )}
          {headlines.map((headline, index) => (
            <LeaderboardItem
              key={headline.id}
              headline={headline}
              rank={index}
              now={now}
            />
          ))}
        </div>
      </div>
    );
  }
);
Leaderboard.displayName = "Leaderboard";

// bubble/visualisation window components
interface BubbleProps {
  bubble: BubbleState;
  onClick: (bubble: BubbleState) => void;
  onHoverStart: (e: React.MouseEvent, bubble: BubbleState) => void;
  onHoverEnd: () => void;
}

const Bubble = React.memo(
  ({ bubble, onClick, onHoverStart, onHoverEnd }: BubbleProps) => {
    return (
      <div
        className={`bubble ${bubble.size} ${bubble.colorClass} ${bubble.state === "fading" ? "fading" : ""
          }`}
        style={{ left: bubble.x, top: bubble.y }}
        onMouseEnter={(e) => onHoverStart(e, bubble)}
        onMouseLeave={onHoverEnd}
        onClick={() => onClick(bubble)}
      >
        {truncateForBubble(bubble.title, bubble.size)}
      </div>
    );
  }
);
Bubble.displayName = "Bubble";

interface VisualizationProps {
  bubbles: BubbleState[];
  onBubbleClick: (bubble: BubbleState) => void;
  onBubbleHoverStart: (e: React.MouseEvent, bubble: BubbleState) => void;
  onBubbleHoverEnd: () => void;
  visContainerRef: React.RefObject<HTMLDivElement | null>;
}

const Visualization = React.memo(
  ({
    bubbles,
    onBubbleClick,
    onBubbleHoverStart,
    onBubbleHoverEnd,
    visContainerRef,
  }: VisualizationProps) => {
    return (
      <div className="visualization-container" ref={visContainerRef}>
        {bubbles.map((bubble) => (
          <Bubble
            key={bubble.id}
            bubble={bubble}
            onClick={onBubbleClick}
            onHoverStart={onBubbleHoverStart}
            onHoverEnd={onBubbleHoverEnd}
          />
        ))}
      </div>
    );
  }
);
Visualization.displayName = "Visualization";


// stats component
interface StatsProps {
  stats: StatsState;
  bubbleCount: number;
  edinburghMode: boolean;
}

const Stats = React.memo(
  ({ stats, bubbleCount, edinburghMode }: StatsProps) => {
    return (
     <div className="stats">
        <div className="stats-group-left">
          <div className="stat-box">
            <strong id="edit-count">{stats.totalEdits}</strong> edits received
          </div>
          {edinburghMode && (
            <div className="stat-box">
              <strong>{stats.filteredByEdinburgh || 0}</strong> filtered by
              Edinburgh
            </div>
          )}
        </div>

        <div className="stats-group-right">
          <div className="stat-box sentiment-positive">
            <strong>{stats.positiveCount}</strong> positive
          </div>
          <div className="stat-box sentiment-neutral">
            <strong>{stats.neutralCount}</strong> neutral
          </div>
          <div className="stat-box sentiment-negative">
            <strong>{stats.negativeCount}</strong> negative
          </div>
        </div>
        
      </div>
    );
  }
);
Stats.displayName = "Stats";

// use edinburgh mode body class when toggled 
function useEdinburghBodyClass(edinburghMode: boolean) {
  useEffect(() => {
    const bodyClass = "edinburgh-mode";
    if (edinburghMode) {
      document.body.classList.add(bodyClass);
    } else {
      document.body.classList.remove(bodyClass);
    }
    return () => {
      document.body.classList.remove(bodyClass);
    };
  }, [edinburghMode]);
}

// main app components
function App() {
  const [edinburghMode, setEdinburghMode] = useState(false);
  const visContainerRef = useRef<HTMLDivElement>(null);

  // hooks
  const { status, stats, headlines, bubbles } = useWikipediaEdits(
    edinburghMode,
    visContainerRef
  );
  const now = useTimeAgo(10000);
  const { tooltip, showTooltip, hideTooltip, mouseMoveProps } = useTooltip();
  useEdinburghBodyClass(edinburghMode);

  // event handlers
  const handleBubbleHoverStart = useCallback(
    (e: React.MouseEvent, bubble: BubbleState) => {
      const data = bubble.rawData;
      const changeText =
        bubble.changeSize > 0 ? `+${bubble.changeSize}` : bubble.changeSize;

      let edinburghInfo = "";
      if (edinburghMode && typeof bubble.edinburghDegrees === "number") {
        if (bubble.edinburghDegrees === 1) {
          edinburghInfo = `<strong>🏴󠁧󠁢󠁳󠁣󠁴󠁿 Edinburgh Degrees:</strong> <span style="color: #8b6f47; font-weight: 600;">1 (Direct link)</span><br>`;
        } else if (bubble.edinburghDegrees <= 4) {
          edinburghInfo = `<strong>🏴󠁧󠁢󠁳󠁣󠁴󠁿 Edinburgh Degrees:</strong> <span style="color: #8b6f47; font-weight: 600;">${bubble.edinburghDegrees}</span><br>`;
        } else if (bubble.edinburghDegrees === 999) {
          edinburghInfo = `<strong>🏴󠁧󠁢󠁳󠁣󠁴󠁿 Edinburgh Degrees:</strong> <span style="color: #999;">Not connected</span><br>`;
        }
      }

      let sentimentInfo = "";
      if (bubble.sentiment) {
        const score = (bubble.sentiment.compound * 100).toFixed(0);
        let sentimentText = "Neutral";
        let sentimentColor = "#d4a853";
        if (bubble.sentiment.compound > 0.05) {
          sentimentText = "Positive";
          sentimentColor = "#5a7eb8";
        } else if (bubble.sentiment.compound < -0.05) {
          sentimentText = "Negative";
          sentimentColor = "#c94343";
        }
        sentimentInfo = `<strong>Sentiment:</strong> <span style="color: ${sentimentColor}; font-weight: 600;">${sentimentText} (${score}%)</span><br>`;
      }

      const content = `
        <strong>${escapeHtml(data.title)}</strong><br>
        ${sentimentInfo} 
        ${edinburghInfo}
        <strong>User:</strong> ${escapeHtml(data.user || "Anonymous")}<br>
        <strong>Change:</strong> ${changeText} bytes<br>
        <strong>Wiki:</strong> ${data.wiki || "unknown"}<br>
        ${data.comment
          ? `<strong>Comment:</strong> ${escapeHtml(
            data.comment.substring(0, 100)
          )}`
          : ""
        }
      `;
      showTooltip(content, e);
    },
    [edinburghMode, showTooltip]
  );

  const handleBubbleClick = (bubble: BubbleState) => {
    const { rawData } = bubble;
    if (!rawData.revision || !rawData.revision.new) {
      console.warn("No revision data found, cannot open link.", rawData);
      return;
    }
    const host = rawData.wiki.replace("wiki", ".wikipedia.org");
    const url = `https://${host}/w/index.php?diff=${rawData.revision.new}&oldid=${rawData.revision.old || ''}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // render output
  return (
    <>
      <Tooltip
        visible={tooltip.visible}
        x={tooltip.x}
        y={tooltip.y}
        content={tooltip.content}
      />

      <main {...mouseMoveProps}>
        <Header
          status={status}
          edinburghMode={edinburghMode}
          onEdinburghModeChange={setEdinburghMode}
        />

        <div className="container">
          <div className="content-row">
            <Leaderboard headlines={headlines} now={now} />

            <div className="main-content">
              <Visualization
                bubbles={bubbles}
                onBubbleClick={handleBubbleClick}
                onBubbleHoverStart={handleBubbleHoverStart}
                onBubbleHoverEnd={hideTooltip}
                visContainerRef={visContainerRef}
              />
              <Stats
                stats={stats}
                bubbleCount={bubbles.length}
                edinburghMode={edinburghMode}
              />
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

export default App;

