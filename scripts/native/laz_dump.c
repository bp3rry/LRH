/* Dump a LAZ/LAS file to a compact binary for numpy, via the LASzip 3.5 API.
 *
 * lazrs/laspy cannot read the StratMap 2025 tiles (LAStools 2023, Point14 item v4);
 * LASzip 3.5 can. Output: a 64-byte header (8 doubles: x/y/z scale, x/y/z offset,
 * point count, reserved) then per point: int32 X, Y, Z, uint8 class, uint8 returns
 * (return number << 4 | number of returns). Real coordinate = int * scale + offset.
 *
 * Build: clang -O2 -I/opt/homebrew/include/laszip -L/opt/homebrew/lib -llaszip_api \
 *          scripts/native/laz_dump.c -o .build/laz_dump
 * Usage: laz_dump input.laz output.bin
 */
#include <stdio.h>
#include <stdlib.h>
#include <laszip_api.h>

static int fail(laszip_POINTER r, const char *what) {
  laszip_CHAR *msg = NULL;
  if (r) laszip_get_error(r, &msg);
  fprintf(stderr, "laz_dump: %s: %s\n", what, msg ? msg : "unknown error");
  return 1;
}

int main(int argc, char **argv) {
  if (argc != 3) { fprintf(stderr, "usage: laz_dump in.laz out.bin\n"); return 2; }
  /* The API wrapper loads the core LASzip library at run time. */
  if (laszip_load_dll()) return fail(NULL, "load LASzip library");
  laszip_POINTER reader;
  if (laszip_create(&reader)) return fail(NULL, "create");
  laszip_BOOL compressed;
  if (laszip_open_reader(reader, argv[1], &compressed)) return fail(reader, "open");
  laszip_header_struct *h; laszip_point_struct *p;
  laszip_get_header_pointer(reader, &h);
  laszip_get_point_pointer(reader, &p);
  laszip_I64 n = h->number_of_point_records ? h->number_of_point_records
                                            : (laszip_I64)h->extended_number_of_point_records;
  FILE *out = fopen(argv[2], "wb");
  if (!out) return fail(NULL, "open output");
  double head[8] = {h->x_scale_factor, h->y_scale_factor, h->z_scale_factor,
                    h->x_offset, h->y_offset, h->z_offset, (double)n, 0};
  fwrite(head, sizeof head, 1, out);
  unsigned char rec[14];
  for (laszip_I64 i = 0; i < n; i++) {
    if (laszip_read_point(reader)) return fail(reader, "read point");
    int xyz[3] = {p->X, p->Y, p->Z};
    for (int k = 0; k < 12; k++) rec[k] = ((unsigned char *)xyz)[k];
    int extended = p->extended_point_type;
    rec[12] = extended ? p->extended_classification : p->classification;
    int rn = extended ? p->extended_return_number : p->return_number;
    int nr = extended ? p->extended_number_of_returns : p->number_of_returns;
    rec[13] = (unsigned char)((rn << 4) | (nr & 15));
    fwrite(rec, sizeof rec, 1, out);
  }
  fclose(out);
  laszip_close_reader(reader);
  laszip_destroy(reader);
  printf("%lld points\n", (long long)n);
  return 0;
}
