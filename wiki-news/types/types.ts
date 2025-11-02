// data we want from input stream
export interface WikiEditData {
  id: number;
  wiki: string;
  namespace: number;
  type: string;
  title: string;
  comment: string;
  timestamp: number;
  user: string;
  bot: boolean;
  length?: { old: number; new: number };
  revision?: { old: number; new: number };
  edinburghDegrees?: number;
}

export interface BubbleState {
  id: string;
  title: string;
  user: string;
  changeSize: number;
  size: "large" | "medium" | "small" | "tiny";
  colorClass: string;
  x: number;
  y: number;
  state: "appearing" | "visible" | "fading";
  edinburghDegrees?: number;
  rawData: WikiEditData;
  sentiment?: SentimentData;
}


export interface HeadlineState {
  id: string;
  title: string;
  user: string;
  changeSize: number;
  timestamp: Date;
  wiki: string;
  comment: string;
  sentiment?: SentimentData;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface StatsState {
  totalEdits: number;
  queueCount: number;
  lastEdit: string;
  filteredByEdinburgh?: number;
  
  positiveCount: number;
  neutralCount: number;
  negativeCount: number;
}


export interface TooltipState {
  visible: boolean;
  content: string;
  x: number;
  y: number;
}

export interface SentimentData {
  neg: number;
  neu: number;
  pos: number;
  compound: number;
}
