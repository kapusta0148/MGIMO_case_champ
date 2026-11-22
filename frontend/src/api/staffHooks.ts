import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AdminUser,
  AuditItem,
  Lesson,
  StaffAnnouncement,
  StaffGroup,
  StaffRequestDetail,
  StaffRequestSummary,
  StaffSchedule,
  StaffSummary,
  TeacherAssessment,
  TeacherCourse,
  TeacherSheet,
} from "./types";

export const useStaffSummary = () =>
  useQuery({ queryKey: ["staff", "summary"], queryFn: () => api<StaffSummary>("/staff/summary"), refetchInterval: 60_000 });

export const useStaffRequests = (params: { status: string; type: string; q: string }) => {
  const search = new URLSearchParams({ status: params.status });
  if (params.type) search.set("type", params.type);
  if (params.q.trim()) search.set("q", params.q.trim());
  return useQuery({
    queryKey: ["staff", "requests", params],
    queryFn: () => api<{ items: StaffRequestSummary[] }>(`/staff/requests?${search}`).then((d) => d.items),
    placeholderData: (previous) => previous,
  });
};

export const useStaffRequest = (id: number) =>
  useQuery({
    queryKey: ["staff", "request", id],
    queryFn: () => api<{ request: StaffRequestDetail }>(`/staff/requests/${id}`).then((d) => d.request),
  });

function useInvalidateStaff() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["staff"] });
}

export function useStaffRequestAction(id: number) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateStaff();
  return useMutation({
    mutationFn: (input: { kind: "transition"; toStatus: string; comment: string } | { kind: "comment"; comment: string }) =>
      input.kind === "transition"
        ? api<{ request: StaffRequestDetail }>(`/staff/requests/${id}/transition`, {
            method: "POST",
            body: { toStatus: input.toStatus, comment: input.comment },
          })
        : api<{ request: StaffRequestDetail }>(`/staff/requests/${id}/comments`, {
            method: "POST",
            body: { comment: input.comment },
          }),
    onSuccess: (data) => {
      queryClient.setQueryData(["staff", "request", id], data.request);
      invalidate();
    },
  });
}

export const useStaffGroups = () =>
  useQuery({
    queryKey: ["staff", "groups"],
    queryFn: () => api<{ items: StaffGroup[] }>("/staff/groups").then((d) => d.items),
    staleTime: 5 * 60_000,
  });

export const useStaffSchedule = (groupId: number | null, from: string | null) =>
  useQuery({
    queryKey: ["staff", "schedule", groupId, from],
    queryFn: () => api<StaffSchedule>(`/staff/schedule?group=${groupId}${from ? `&from=${from}` : ""}`),
    enabled: groupId !== null,
  });

export type LessonAction =
  | { action: "move"; date: string; startTime: string; endTime: string; room: string; reason: string }
  | { action: "cancel"; reason: string }
  | { action: "restore" };

export function useLessonAction() {
  const invalidate = useInvalidateStaff();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: LessonAction }) =>
      api<{ lesson: Lesson; notified: number }>(`/staff/lessons/${id}`, { method: "PATCH", body }),
    onSuccess: invalidate,
  });
}

export const useStaffAnnouncements = () =>
  useQuery({
    queryKey: ["staff", "announcements"],
    queryFn: () => api<{ items: StaffAnnouncement[] }>("/staff/announcements").then((d) => d.items),
  });

export function useCreateAnnouncement() {
  const invalidate = useInvalidateStaff();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ announcement: StaffAnnouncement; notified: number }>("/staff/announcements", { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export const useTeacherCourses = () =>
  useQuery({
    queryKey: ["teacher", "courses"],
    queryFn: () => api<{ items: TeacherCourse[] }>("/teacher/courses").then((d) => d.items),
  });

export const useTeacherSheet = (id: number) =>
  useQuery({ queryKey: ["teacher", "course", id], queryFn: () => api<TeacherSheet>(`/teacher/courses/${id}`) });

export function useUpdateAssessment(courseId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, score }: { id: number; score: number | null }) =>
      api<{ assessment: TeacherAssessment; changed: boolean; currentScore: number | null }>(`/teacher/assessments/${id}`, {
        method: "PATCH",
        body: { score },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["teacher", "course", courseId] }),
  });
}

export const useAdminUsers = () =>
  useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api<{ items: AdminUser[] }>("/admin/users").then((d) => d.items),
  });

export function useSetUserActive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, isActive }: { id: number; isActive: boolean }) =>
      api<{ user: AdminUser }>(`/admin/users/${id}`, { method: "PATCH", body: { isActive } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export const useAuditLog = () =>
  useQuery({
    queryKey: ["admin", "audit"],
    queryFn: () => api<{ items: AuditItem[] }>("/admin/audit?limit=100").then((d) => d.items),
  });
