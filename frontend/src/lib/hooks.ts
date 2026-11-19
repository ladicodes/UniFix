"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, IS_DEMO } from "./api";
import type { ProfessionalFilters } from "./types";

const poll = IS_DEMO ? false : 5000;

/** Invalidate queries whenever the API change feed fires for a channel. */
export function useLive(channel: string, keys: unknown[][]) {
  const qc = useQueryClient();
  useEffect(() => {
    const off = api.subscribe(channel, () => keys.forEach((k) => qc.invalidateQueries({ queryKey: k })));
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel, qc]);
}

export function useGlobalLive() {
  const qc = useQueryClient();
  useEffect(() => api.subscribe("*", () => qc.invalidateQueries()), [qc]);
}

export const useProfessionals = (f: ProfessionalFilters) =>
  useQuery({ queryKey: ["professionals", f], queryFn: () => api.listProfessionals(f), placeholderData: (p) => p });

export const useProfessional = (id: string) =>
  useQuery({ queryKey: ["professional", id], queryFn: () => api.getProfessional(id), enabled: Boolean(id) });

export const useReviews = (id: string) => useQuery({ queryKey: ["reviews", id], queryFn: () => api.listReviews(id) });

export const useConversations = (enabled = true) =>
  useQuery({ queryKey: ["conversations"], queryFn: () => api.listConversations(), enabled, refetchInterval: poll });

export function useConversation(id: string) {
  useLive(`conversation:${id}`, [["conversation", id], ["conversations"]]);
  return useQuery({ queryKey: ["conversation", id], queryFn: () => api.getConversation(id) });
}

export const useBookings = (enabled = true) =>
  useQuery({ queryKey: ["bookings"], queryFn: () => api.listBookings(), enabled, refetchInterval: poll });

export function useBooking(id: string) {
  useLive(`booking:${id}`, [["booking", id], ["bookings"]]);
  return useQuery({
    queryKey: ["booking", id],
    queryFn: () => api.getBooking(id),
    // live mode: poll while a chain transaction is waiting for confirmation
    refetchInterval: (q) => (!IS_DEMO && q.state.data?.escrow?.reconciliation === "PENDING_CONFIRMATION" ? 2500 : poll),
  });
}

export const useNotifications = (enabled = true) =>
  useQuery({ queryKey: ["notifications"], queryFn: () => api.listNotifications(), enabled, refetchInterval: IS_DEMO ? false : 15000 });

export const useDisputes = () => useQuery({ queryKey: ["disputes"], queryFn: () => api.listDisputes() });

export function useAction<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries() });
}
