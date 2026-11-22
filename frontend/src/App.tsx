import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import type { Role } from "./api/types";
import { homePath, useAuth } from "./auth/AuthContext";
import { StudentLayout } from "./components/Layout";
import { StaffLayout } from "./components/StaffLayout";
import { Button, Skeleton } from "./components/ui";
import { GradesPage } from "./pages/Grades";
import { PlannerPage } from "./pages/Planner";
import { LoginPage } from "./pages/Login";
import { AnnouncementPage, NotFoundPage, NotificationsPage, ProfilePage } from "./pages/Other";
import { RequestDetailPage, RequestNewPage, RequestsPage } from "./pages/Requests";
import { SchedulePage } from "./pages/Schedule";
import { TodayPage } from "./pages/Today";
import { StaffOverviewPage, StaffRequestPage, StaffRequestsPage } from "./pages/staff/Requests";
import { StaffAnnouncementsPage, StaffSchedulePage } from "./pages/staff/Schedule";
import {
  AdminAuditPage,
  AdminUsersPage,
  TeacherCoursePage,
  TeacherCoursesPage,
} from "./pages/staff/TeacherAdmin";

/** Пускает только вошедших с подходящей ролью. Это удобство интерфейса: настоящая проверка — на сервере. */
function Protected({ roles }: { roles: Role[] }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (!roles.includes(user.role)) return <Navigate to={homePath(user)} replace />;
  return <Outlet />;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? homePath(user) : "/login"} replace />;
}

export function App() {
  const { loading, bootError, retryBoot } = useAuth();

  if (loading)
    return (
      <main className="mx-auto w-full max-w-md px-4 py-10">
        <Skeleton rows={3} />
      </main>
    );
  if (bootError)
    return (
      <main className="mx-auto grid min-h-dvh w-full max-w-md content-center gap-3 px-4 text-center">
        <h1 className="m-0 text-xl font-bold">Не удалось связаться с сервером</h1>
        <p className="m-0 text-sm text-muted">{bootError}</p>
        <Button onClick={retryBoot}>Повторить</Button>
      </main>
    );

  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected roles={["student"]} />}>
        <Route element={<StudentLayout />}>
          <Route path="/today" element={<TodayPage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/planner" element={<PlannerPage />} />
          <Route path="/grades" element={<GradesPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/requests/new" element={<RequestNewPage />} />
          <Route path="/requests/:id" element={<RequestDetailPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/announcements/:id" element={<AnnouncementPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Route>
      </Route>
      <Route element={<Protected roles={["dean_staff", "admin"]} />}>
        <Route element={<StaffLayout />}>
          <Route path="/staff" element={<StaffOverviewPage />} />
          <Route path="/staff/requests" element={<StaffRequestsPage />} />
          <Route path="/staff/requests/:id" element={<StaffRequestPage />} />
          <Route path="/staff/schedule" element={<StaffSchedulePage />} />
          <Route path="/staff/announcements" element={<StaffAnnouncementsPage />} />
        </Route>
      </Route>
      <Route element={<Protected roles={["admin"]} />}>
        <Route element={<StaffLayout />}>
          <Route path="/admin/users" element={<AdminUsersPage />} />
          <Route path="/admin/audit" element={<AdminAuditPage />} />
        </Route>
      </Route>
      <Route element={<Protected roles={["teacher"]} />}>
        <Route element={<StaffLayout />}>
          <Route path="/teacher" element={<TeacherCoursesPage />} />
          <Route path="/teacher/courses/:id" element={<TeacherCoursePage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
