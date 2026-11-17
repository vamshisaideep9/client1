"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import {
  correctApprovedSubmission,
  submitProperty,
  updateSubmission,
  uploadPropertyMedia,
  type Submission,
} from "@/lib/property-submissions-api";
import {
  buildSubmissionPayload,
  buildSubmissionUpdatePayload,
  validateForm,
  EMPTY_FORM,
  submissionIssuesToFieldErrors,
  submissionToFormState,
  type PropertyDetailForm,
  type SubmitFormState,
} from "@/lib/property-submit";
import { firstPanoramaError } from "@/lib/panorama-check";

export function useSubmitProperty(
  submission?: Submission,
  { adminCorrection = false }: { adminCorrection?: boolean } = {},
) {
  const router = useRouter();
  const [form, setForm] = React.useState<SubmitFormState>(() =>
    submission ? submissionToFormState(submission) : EMPTY_FORM,
  );
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitting, setSubmitting] = React.useState(false);
  const [uploadProgress, setUploadProgress] = React.useState<string | null>(null);
  const [correctionReason, setCorrectionReason] = React.useState("");

  const setField = React.useCallback(
    <K extends keyof SubmitFormState>(field: K, value: SubmitFormState[K]) => {
      setForm((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const setDetailField = React.useCallback(
    <K extends keyof PropertyDetailForm>(field: K, value: PropertyDetailForm[K]) => {
      setForm((prev) => ({ ...prev, details: { ...prev.details, [field]: value } }));
    },
    [],
  );

  const addAmenity = React.useCallback((value: string) => {
    const v = value.trim();
    if (v === "") return;
    setForm((prev) =>
      prev.amenities.includes(v) ? prev : { ...prev, amenities: [...prev.amenities, v] },
    );
  }, []);
  const removeAmenity = React.useCallback((value: string) => {
    setForm((prev) => ({ ...prev, amenities: prev.amenities.filter((a) => a !== value) }));
  }, []);

  const setImages = React.useCallback((images: File[]) => {
    setForm((prev) => ({ ...prev, images }));
  }, []);
  const setDocuments = React.useCallback((documents: File[]) => {
    setForm((prev) => ({ ...prev, documents }));
  }, []);
  const setPanoramas = React.useCallback((panoramas: File[]) => {
    setForm((prev) => ({ ...prev, panoramas }));
  }, []);

  // A 422 the client checks missed is shown on the field it belongs to, not as
  // a bare "Input should be greater than 0" toast with no field named.
  const showFieldIssues = React.useCallback(
    (res: { ok: false; issues?: { field: string; message: string }[] }): boolean => {
      const fieldErrors = submissionIssuesToFieldErrors(res.issues);
      if (Object.keys(fieldErrors).length === 0) return false;
      setErrors(fieldErrors);
      toast.error("Please fix the highlighted fields.");
      return true;
    },
    [],
  );

  const submit = React.useCallback(async () => {
    const found = validateForm(form, { requireImages: submission == null });
    if (adminCorrection && correctionReason.trim() === "") {
      found.correctionReason = "Correction reason is required.";
    }
    setErrors(found);
    if (Object.keys(found).length > 0) {
      toast.error("Please fix the highlighted fields.");
      return;
    }
    setSubmitting(true);
    if (submission) {
      setUploadProgress(adminCorrection ? "Staging correction" : "Saving changes");
      const updatePayload = buildSubmissionUpdatePayload(form);
      const res = adminCorrection
        ? await correctApprovedSubmission(submission.id, {
            ...updatePayload,
            reason: correctionReason.trim(),
          })
        : await updateSubmission(submission.id, updatePayload);
      setSubmitting(false);
      setUploadProgress(null);
      if (res.ok) {
        if (adminCorrection) {
          toast.success("Correction staged for RERA review. The current listing remains live.");
          router.push("/dashboard/property-review");
        } else {
          toast.success(
            submission.status === "approved"
              ? "Changes sent for Admin review. The approved version remains public."
              : "Listing changes saved for review.",
          );
          router.push("/dashboard/my-submissions");
        }
      } else if (!showFieldIssues(res)) {
        toast.error(res.error || "Could not update the listing.");
      }
      return;
    }
    // Catch a wrongly shaped 360 image before any upload starts.
    const panoramaError = await firstPanoramaError(form.panoramas);
    if (panoramaError) {
      setSubmitting(false);
      setErrors({ panoramas: panoramaError });
      toast.error("Please fix the highlighted fields.");
      return;
    }
    const totalUploads = form.images.length + form.documents.length + form.panoramas.length;
    setUploadProgress(`Uploading 0 of ${totalUploads}`);
    const uploaded = await uploadPropertyMedia(
      form.images,
      form.documents,
      form.panoramas,
      (done, total) => setUploadProgress(`Uploading ${done} of ${total}`),
    );
    if (!uploaded.ok) {
      setSubmitting(false);
      setUploadProgress(null);
      toast.error(uploaded.error);
      return;
    }
    setUploadProgress("Saving submission");
    const res = await submitProperty(buildSubmissionPayload(form, uploaded.media));
    setSubmitting(false);
    setUploadProgress(null);
    if (res.ok) {
      toast.success("Listing submitted for review.");
      router.push("/dashboard/my-submissions");
    } else if (!showFieldIssues(res)) {
      toast.error(res.error || "Could not submit the listing.");
    }
  }, [adminCorrection, correctionReason, form, router, showFieldIssues, submission]);

  return {
    form,
    setField,
    setDetailField,
    addAmenity,
    removeAmenity,
    setImages,
    setDocuments,
    setPanoramas,
    adminCorrection,
    correctionReason,
    setCorrectionReason,
    editing: submission != null,
    existingMedia: submission?.media ?? [],
    errors,
    submitting,
    uploadProgress,
    submit,
  };
}
