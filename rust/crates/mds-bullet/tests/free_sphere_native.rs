#[path = "../examples/free_sphere_oracle.rs"]
mod oracle;

#[test]
fn native_shim_still_matches_the_recorded_pilot_oracle() {
    let actual = oracle::capture();
    let expected = include_str!("data/free-sphere-native.tsv");
    for (frame, (a, e)) in actual.lines().zip(expected.lines()).enumerate() {
        assert_eq!(a, e, "native oracle row {frame}");
    }
    assert_eq!(actual.lines().count(), expected.lines().count());
}
