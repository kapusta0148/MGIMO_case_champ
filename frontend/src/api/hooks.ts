import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Announcement,
  Dashboard,
  Grades,
  Lesson,
  Notification,
  RequestDetail,
  RequestSummary,
  RequestType,
  Schedule,
} from "./types";

export const useDashboard = () =>
  useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/me/dashboard"), refetchInterval: 60_000 });

export const useSchedule = (from: string | null, to: string | null) =>
  useQuery({
    queryKey: ["schedule", from, to],
    queryFn: () => api<Schedule>(from && to ? `/me/schedule?from=${from}&to=${to}` : "/me/schedule"),
  });

export const useLesson = (id: number | null) =>
  useQuery({
    queryKey: ["lesson", id],
    queryFn: () => api<{ lesson: Lesson }>(`/me/lessons/${id}`).then((d) => d.lesson),
    enabled: id !== null,
  });

export const useGrades = () => useQuery({ queryKey: ["grades"], queryFn: () => api<Grades>("/me/grades") });

export const useRequests = () =>
  useQuery({
    queryKey: ["requests"],
    queryFn: () => api<{ items: RequestSummary[] }>("/me/requests").then((d) => d.items),
  });

export const useRequest = (id: number) =>
  useQuery({
    queryKey: ["request", id],
    queryFn: () => api<{ request: RequestDetail }>(`/me/requests/${id}`).then((d) => d.request),
  });

export const useRequestTypes = () =>
  useQuery({
    queryKey: ["request-types"],
    queryFn: () => api<{ items: RequestType[] }>("/meta/request-types").then((d) => d.items),
    staleTime: Infinity,
  });

export function useCreateRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { payload: unknown; idempotencyKey: string }) =>
      api<{ request: RequestDetail; created: boolean }>("/me/requests", {
        method: "POST",
        body: input.payload,
        headers: { "Idempotency-Key": input.idempotencyKey },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["request", data.request.id], data.request);
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useCommentRequest(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (comment: string) =>
      api<{ request: RequestDetail }>(`/me/requests/${id}/comments`, { method: "POST", body: { comment } }),
    onSuccess: (data) => {
      queryClient.setQueryData(["request", id], data.request);
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

type NotificationFeed = { items: Notification[]; unreadCount: number };

export const useNotifications = () =>
  useQuery({
    queryKey: ["notifications"],
    queryFn: () => api<NotificationFeed>("/me/notifications"),
    refetchInterval: 60_000,
  });

export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api<{ unreadCount: number }>(`/me/notifications/${id}/read`, { method: "PATCH" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useMarkAllRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ unreadCount: number }>("/me/notifications/read-all", { method: "POST" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export const useAnnouncement = (id: number) =>
  useQuery({
    queryKey: ["announcement", id],
    queryFn: () => api<{ announcement: Announcement }>(`/me/announcements/${id}`).then((d) => d.announcement),
  });
