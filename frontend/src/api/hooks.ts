import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  Announcement,
  Dashboard,
  Grades,
  Lesson,
  Notification,
  PersonalTask,
  Planner,
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

// ── Планировщик и личные задачи ───────────────────────────────────────────────

export const usePlanner = () => useQuery({ queryKey: ["planner"], queryFn: () => api<Planner>("/me/planner") });

export const useTasks = () =>
  useQuery({
    queryKey: ["tasks"],
    queryFn: () => api<{ items: PersonalTask[] }>("/me/tasks").then((d) => d.items),
  });

function useInvalidatePlan() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["planner"] });
  };
}

export function useCreateTask() {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ task: PersonalTask; created: boolean }>("/me/tasks", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useToggleTask() {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: ({ id, completed }: { id: number; completed: boolean }) =>
      api<{ task: PersonalTask }>(`/me/tasks/${id}`, { method: "PATCH", body: { completed } }),
    onSuccess: invalidate,
  });
}

export function useDeleteTask() {
  const invalidate = useInvalidatePlan();
  return useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/me/tasks/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
}
