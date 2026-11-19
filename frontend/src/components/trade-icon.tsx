import { Car, Droplets, Fuel, Hammer, PaintRoller, Snowflake, Sparkles, Zap, type LucideIcon } from "lucide-react";
import type { CategoryId } from "@/lib/types";

export const TRADE_ICON: Record<CategoryId, LucideIcon> = {
  electrician: Zap,
  plumber: Droplets,
  "ac-technician": Snowflake,
  mechanic: Car,
  generator: Fuel,
  carpenter: Hammer,
  cleaner: Sparkles,
  painter: PaintRoller,
};
