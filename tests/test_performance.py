import unittest

from berofel.services.performance import profile_for_resources, qwen_limits, qwen_threads


GIB = 1024 ** 3


class PerformanceProfileTests(unittest.TestCase):
    def test_low_memory_or_two_core_machine_keeps_resources_reserved(self):
        for cpus, total, available in ((2, 16*GIB, 12*GIB),
                                       (8, 8*GIB, 1*GIB),
                                       (8, 4*GIB, 3*GIB)):
            with self.subTest(cpus=cpus, total=total, available=available):
                profile = profile_for_resources(cpus, total, available)
                self.assertEqual(profile.level, 'economia')
                self.assertEqual(profile.preview_threads, 1)
                self.assertLess(profile.ai_threads, cpus)
                self.assertLessEqual(profile.export_threads, 2)

    def test_midrange_machine_uses_balanced_parallelism(self):
        profile = profile_for_resources(8, 16*GIB, 5*GIB)
        self.assertEqual(profile.level, 'equilibrado')
        self.assertEqual(profile.preview_threads, 2)
        self.assertEqual(profile.ai_threads, 4)
        self.assertEqual(profile.export_threads, 6)

    def test_workstation_scales_up_without_using_every_core(self):
        profile = profile_for_resources(24, 64*GIB, 32*GIB)
        self.assertEqual(profile.level, 'desempenho')
        self.assertEqual(profile.preview_threads, 4)
        self.assertEqual(profile.ai_threads, 8)
        self.assertEqual(profile.export_threads, 16)
        self.assertLess(profile.ai_threads, profile.logical_cpus)

    def test_qwen_scales_to_twelve_threads_only_with_cpu_and_memory_headroom(self):
        ryzen=profile_for_resources(16,15_743*1024**2,8_230*1024**2)
        self.assertEqual(ryzen.level,'equilibrado')
        self.assertEqual(ryzen.ai_threads,4)
        self.assertEqual(qwen_threads(ryzen),12)
        twelve_core=profile_for_resources(12,32*GIB,16*GIB)
        self.assertEqual(qwen_threads(twelve_core),8)
        workstation=profile_for_resources(24,64*GIB,32*GIB)
        self.assertEqual(qwen_threads(workstation),12)
        low_memory=profile_for_resources(16,16*GIB,5*GIB)
        self.assertEqual(qwen_threads(low_memory),low_memory.ai_threads)
        modest=profile_for_resources(8,8*GIB,3*GIB)
        self.assertEqual(qwen_threads(modest),modest.ai_threads)

    def test_qwen_context_and_batches_adapt_to_available_memory(self):
        low=profile_for_resources(8,8*GIB,700*1024**2)
        economy=profile_for_resources(8,8*GIB,2500*1024**2)
        balanced=profile_for_resources(8,16*GIB,5*GIB)
        workstation=profile_for_resources(24,64*GIB,32*GIB)
        self.assertEqual(qwen_limits(low),(2048,4096))
        self.assertEqual(qwen_limits(economy),(4096,8192))
        self.assertEqual(qwen_limits(balanced),(8192,16384))
        self.assertEqual(qwen_limits(workstation),(16384,32768))


if __name__ == '__main__':
    unittest.main()
